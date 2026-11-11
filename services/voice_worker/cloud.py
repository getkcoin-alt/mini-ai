"""API providers for Mini's "api" infrastructure (see infra.py).

- hearing: Groq Whisper (OpenAI-compatible /audio/transcriptions)
- thinking: Groq / Gemini / OpenRouter (OpenAI-compatible streaming chat)
- voice: hosted Chatterbox at Resemble, cloned from Mini's same reference clip,
  streamed as PCM and converted to the 24 kHz Mini plays everywhere; or
  ElevenLabs (a voice from the admin's My Voices), streamed as raw 24 kHz PCM.

Keys come only from the worker environment; they are never logged or returned.
Transcripts and replies are never logged here either.
"""
from __future__ import annotations

import io
import json
import os
import re
import struct
import wave
from typing import AsyncIterator

import httpx
import numpy as np

from . import infra

OUTPUT_RATE = 24000
RESEMBLE_RATE = 48000  # Resemble streams 8k..48k; 48k halves cleanly to 24k


class ProviderError(RuntimeError):
    """An API stage failed; the caller falls back to the local model."""


def _timeout(seconds: float) -> httpx.Timeout:
    return httpx.Timeout(seconds, connect=min(5.0, seconds))


def _wav16k(samples: np.ndarray) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes((np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes())
    return buf.getvalue()


REST_STATUSES = {401, 402, 403, 429}


def _retry_after(resp) -> float | None:
    try:
        return float(resp.headers.get("retry-after", ""))
    except ValueError:
        return None


async def transcribe(samples: np.ndarray, model: str = infra.STT_MODEL_DEFAULT) -> str:
    """16 kHz float32 speech -> text via Groq Whisper, rotating across Groq keys."""
    keys = infra.usable_keys("groq")
    if not keys:
        raise ProviderError("no groq key available")
    audio = _wav16k(samples)
    last = "no groq key available"
    async with httpx.AsyncClient(timeout=_timeout(10), trust_env=False) as client:
        for name, key in keys:
            try:
                resp = await client.post(
                    infra.LLM_PROVIDERS["groq"]["base"] + "/audio/transcriptions",
                    headers={"Authorization": f"Bearer {key}"},
                    files={"file": ("speech.wav", audio, "audio/wav")},
                    data={"model": model, "language": "en", "response_format": "json", "temperature": "0"},
                )
            except httpx.HTTPError as exc:
                last = f"stt {type(exc).__name__}"
                continue
            if resp.status_code == 200:
                return str(resp.json().get("text") or "").strip()
            last = f"stt http {resp.status_code}"
            if resp.status_code in REST_STATUSES or resp.status_code >= 500:
                infra.rest_key(name, resp.status_code, _retry_after(resp))
                continue
            break  # 400/404: wrong model or audio; another key will not help
    raise ProviderError(last)


def parse_sse_line(line: str) -> tuple[str, bool]:
    """(content delta, finished) from one OpenAI-style server-sent-event line."""
    line = line.strip()
    if not line.startswith("data:"):
        return "", False
    data = line[5:].strip()
    if data == "[DONE]":
        return "", True
    try:
        chunk = json.loads(data)
    except ValueError:
        return "", False
    choices = chunk.get("choices") or [{}]
    delta = (choices[0].get("delta") or {}).get("content") or ""
    return delta, bool(choices[0].get("finish_reason"))


class ModelError(ProviderError):
    """This model cannot be used (missing, retired, bad request): skip it, keep the keys."""


async def chat_stream(provider: str, model: str, messages: list[dict], *, max_tokens: int,
                      temperature: float = 0.6) -> AsyncIterator[str]:
    """Stream reply text from an OpenAI-compatible provider, rotating across its keys."""
    spec = infra.LLM_PROVIDERS.get(provider)
    keys = infra.usable_keys(provider) if spec else []
    if not keys:
        raise ProviderError(f"no {provider} key available")
    body = {"model": model, "messages": messages, "stream": True, "max_tokens": max_tokens,
            "temperature": temperature}
    last = f"no {provider} key available"
    async with httpx.AsyncClient(timeout=_timeout(30), trust_env=False) as client:
        for name, key in keys:
            headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            if provider == "openrouter":
                headers["X-Title"] = "Mini"
            produced = False
            try:
                async with client.stream("POST", spec["base"] + "/chat/completions", headers=headers, json=body) as resp:
                    if resp.status_code != 200:
                        last = f"{provider} http {resp.status_code}"
                        if resp.status_code in REST_STATUSES or resp.status_code >= 500:
                            infra.rest_key(name, resp.status_code, _retry_after(resp))
                            continue
                        raise ModelError(f"{provider} {model} http {resp.status_code}")
                    async for line in resp.aiter_lines():
                        delta, finished = parse_sse_line(line)
                        if delta:
                            produced = True
                            yield delta
                        if finished:
                            return
                    if produced:
                        return
                    last = f"{provider} empty reply"
            except httpx.HTTPError as exc:
                if produced:
                    raise ProviderError(f"{provider} {type(exc).__name__}") from None
                last = f"{provider} {type(exc).__name__}"
    raise ProviderError(last)


async def chat_routed(plan: dict, messages: list[dict], *, max_tokens: int) -> AsyncIterator[str]:
    """Free-model routing: chosen model -> lighter model -> other providers. Raises if all fail."""
    route = infra.llm_route(plan)
    if not route:
        raise ProviderError("no api key for any provider")
    last = "no route"
    for provider, model in route:
        produced = False
        try:
            async for delta in chat_stream(provider, model, messages, max_tokens=max_tokens):
                produced = True
                yield delta
            return
        except ProviderError as exc:
            if produced:
                raise
            last = str(exc)
            infra.record("route", "llm", f"{provider}/{model}"[:40], last)
    raise ProviderError(last)


class WavStreamDecoder:
    """Turn a streamed WAV (header + extra chunks + PCM16 data) into 24 kHz float32."""

    def __init__(self):
        self.head = b""
        self.in_data = False
        self.rate = RESEMBLE_RATE
        self.carry = b""
        self._odd = None

    def feed(self, chunk: bytes) -> np.ndarray | None:
        if not self.in_data:
            self.head += chunk
            if len(self.head) < 12:
                return None
            if self.head[:4] != b"RIFF" or self.head[8:12] != b"WAVE":
                raise ProviderError("tts not wav")
            pos = 12
            while pos + 8 <= len(self.head):
                cid, size = self.head[pos:pos + 4], struct.unpack("<I", self.head[pos + 4:pos + 8])[0]
                if cid == b"fmt " and pos + 16 <= len(self.head):
                    channels, rate, bits = (struct.unpack("<H", self.head[pos + 10:pos + 12])[0],
                                            struct.unpack("<I", self.head[pos + 12:pos + 16])[0],
                                            struct.unpack("<H", self.head[pos + 22:pos + 24])[0]
                                            if pos + 24 <= len(self.head) else 16)
                    if channels != 1 or bits != 16:
                        raise ProviderError("tts format")
                    self.rate = rate
                if cid == b"data":
                    self.in_data = True
                    chunk, self.head = self.head[pos + 8:], b""
                    break
                if pos + 8 + size > len(self.head):
                    return None  # wait for the rest of this chunk
                pos += 8 + size + (size & 1)
            if not self.in_data:
                return None
        data = self.carry + chunk
        usable = len(data) - (len(data) % 2)
        self.carry = data[usable:]
        if not usable:
            return None
        samples = np.frombuffer(data[:usable], dtype="<i2").astype(np.float32) / 32768.0
        return self._to_24k(samples)

    def _to_24k(self, samples: np.ndarray) -> np.ndarray | None:
        if self.rate == OUTPUT_RATE:
            return samples
        if self.rate == 48000:
            if self._odd is not None:
                samples = np.concatenate([[self._odd], samples])
            self._odd = samples[-1] if len(samples) % 2 else None
            even = samples[: len(samples) - (len(samples) % 2)]
            return even.reshape(-1, 2).mean(axis=1) if len(even) else None
        # any other rate: linear resample (rare; Mini asks for 48 kHz)
        n = int(round(len(samples) * OUTPUT_RATE / self.rate))
        if n <= 1:
            return None
        return np.interp(np.linspace(0, len(samples) - 1, n), np.arange(len(samples)), samples).astype(np.float32)


class PcmStreamDecoder:
    """Raw little-endian PCM16 (any chunking) -> float32, keeping an odd byte for the next chunk."""

    def __init__(self):
        self.carry = b""

    def feed(self, chunk: bytes) -> np.ndarray | None:
        data = self.carry + chunk
        usable = len(data) - (len(data) % 2)
        self.carry = data[usable:]
        if not usable:
            return None
        return np.frombuffer(data[:usable], dtype="<i2").astype(np.float32) / 32768.0


ELEVENLABS_API = "https://api.elevenlabs.io"
ELEVENLABS_MODEL = "eleven_flash_v2_5"  # their fastest model; costs half a credit per character


def _elevenlabs_status(status: int, body: bytes) -> int:
    """ElevenLabs reports an empty quota as 401 "quota_exceeded": treat that as out of credit."""
    if status == 401 and b"quota_exceeded" in body[:2000]:
        return 402
    return status


async def speak_stream(text: str, provider: str = "resemble") -> AsyncIterator[np.ndarray]:
    """Mini's voice for `text` from the chosen hosted voice, as 24 kHz float32 chunks."""
    if provider == "elevenlabs":
        async for samples in _elevenlabs_stream(text):
            yield samples
        return
    async for samples in _resemble_stream(text):
        yield samples


async def _elevenlabs_stream(text: str) -> AsyncIterator[np.ndarray]:
    if not infra.voice_ready("elevenlabs"):
        raise ProviderError("elevenlabs key missing or resting")
    voice_id = infra.secret("MINI_ELEVENLABS_VOICE_ID")
    if not re.match(r"^[A-Za-z0-9]{8,64}$", voice_id):
        raise ProviderError("elevenlabs voice id looks wrong")
    model = os.environ.get("MINI_ELEVENLABS_MODEL", ELEVENLABS_MODEL)
    decoder = PcmStreamDecoder()
    try:
        async with httpx.AsyncClient(timeout=_timeout(20), trust_env=False) as client:
            async with client.stream(
                    "POST", f"{ELEVENLABS_API}/v1/text-to-speech/{voice_id}/stream",
                    params={"output_format": "pcm_24000"},
                    json={"text": text[:600], "model_id": model},
                    headers={"xi-api-key": infra.secret("MINI_ELEVENLABS_API_KEY"),
                             "Content-Type": "application/json"}) as resp:
                if resp.status_code != 200:
                    status = _elevenlabs_status(resp.status_code, await resp.aread())
                    if status in REST_STATUSES or status >= 500:
                        infra.rest_key("MINI_ELEVENLABS_API_KEY", status, _retry_after(resp))
                    raise ProviderError("elevenlabs out of credit" if status == 402 else f"elevenlabs http {status}")
                async for chunk in resp.aiter_bytes(4800):
                    out = decoder.feed(chunk)
                    if out is not None and len(out):
                        yield out
    except httpx.HTTPError as exc:
        raise ProviderError(f"elevenlabs {type(exc).__name__}") from None


async def _resemble_stream(text: str) -> AsyncIterator[np.ndarray]:
    if not all(infra.has(k) for k in infra.TTS_KEYS):
        raise ProviderError("tts key missing")
    url = os.environ.get("MINI_RESEMBLE_STREAM_URL", "https://f.cluster.resemble.ai/stream")
    body = {"voice_uuid": infra.secret("MINI_RESEMBLE_VOICE_UUID"), "data": text[:600],
            "precision": "PCM_16", "sample_rate": RESEMBLE_RATE}
    if infra.secret("MINI_RESEMBLE_PROJECT_UUID"):
        body["project_uuid"] = infra.secret("MINI_RESEMBLE_PROJECT_UUID")
    decoder = WavStreamDecoder()
    try:
        async with httpx.AsyncClient(timeout=_timeout(20), trust_env=False) as client:
            async with client.stream("POST", url, json=body, headers={
                    "Authorization": f"Bearer {infra.secret('MINI_RESEMBLE_API_KEY')}",
                    "Content-Type": "application/json"}) as resp:
                if resp.status_code != 200:
                    raise ProviderError(f"tts http {resp.status_code}")
                async for chunk in resp.aiter_bytes(4800):
                    out = decoder.feed(chunk)
                    if out is not None and len(out):
                        yield out
    except httpx.HTTPError as exc:
        raise ProviderError(f"tts {type(exc).__name__}") from None


RESEMBLE_API = "https://app.resemble.ai/api/v2"


async def list_models(provider: str, slot: str | None = None) -> list[dict]:
    """Model ids a key can use (doubles as a key check). provider: groq|gemini|openrouter|resemble|elevenlabs."""
    if provider == "elevenlabs":
        if not infra.has("MINI_ELEVENLABS_API_KEY"):
            raise ProviderError("elevenlabs key missing")
        try:
            async with httpx.AsyncClient(timeout=_timeout(10), trust_env=False) as client:
                resp = await client.get(ELEVENLABS_API + "/v1/voices",
                                        headers={"xi-api-key": infra.secret("MINI_ELEVENLABS_API_KEY")})
        except httpx.HTTPError as exc:
            raise ProviderError(f"elevenlabs {type(exc).__name__}") from None
        if resp.status_code != 200:
            raise ProviderError(f"elevenlabs http {resp.status_code}"
                                + (" (the key needs the Voices read permission)" if resp.status_code in (401, 403) else ""))
        return parse_model_list(provider, resp.json())
    if provider == "resemble":
        if not infra.has("MINI_RESEMBLE_API_KEY"):
            raise ProviderError("resemble key missing")
        url, key = RESEMBLE_API + "/voices", infra.secret("MINI_RESEMBLE_API_KEY")
        params = {"page": 1, "page_size": 100}
    else:
        spec = infra.LLM_PROVIDERS.get(provider)
        if not spec:
            raise ProviderError("unknown provider")
        keys = dict(infra.provider_keys(provider))
        if slot:
            if slot not in keys:
                raise ProviderError("that key is not added")
            key = keys[slot]
        elif keys:
            key = next(iter(keys.values()))
        else:
            raise ProviderError(f"{provider} key missing")
        url, params = spec["base"] + "/models", None
    try:
        async with httpx.AsyncClient(timeout=_timeout(10), trust_env=False) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {key}"}, params=params)
    except httpx.HTTPError as exc:
        raise ProviderError(f"{provider} {type(exc).__name__}") from None
    if resp.status_code != 200:
        raise ProviderError(f"{provider} http {resp.status_code}")
    return parse_model_list(provider, resp.json())


def parse_model_list(provider: str, payload) -> list[dict]:
    items = []
    if provider == "elevenlabs":
        # "My Voices" (cloned, designed, saved) first; ElevenLabs' stock voices after.
        for row in (payload or {}).get("voices") or []:
            if isinstance(row, dict) and row.get("voice_id"):
                category = str(row.get("category") or "")
                items.append({"id": str(row["voice_id"])[:64], "name": str(row.get("name") or row["voice_id"])[:80],
                              "mine": category != "premade"})
        return sorted(items, key=lambda r: (not r["mine"], r["name"].lower()))[:200]
    rows = (payload or {}).get("items") if provider == "resemble" else (payload or {}).get("data")
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        if provider == "resemble":
            if row.get("uuid"):
                items.append({"id": str(row["uuid"]), "name": str(row.get("name") or row["uuid"])[:80]})
            continue
        mid = str(row.get("id") or "")
        if provider == "gemini" and mid.startswith("models/"):
            mid = mid[len("models/"):]
        if mid:
            pricing = row.get("pricing") or {}
            free = (mid.endswith(":free") or mid == "openrouter/free"
                    or (str(pricing.get("prompt")) in ("0", "0.0") and str(pricing.get("completion")) in ("0", "0.0")))
            items.append({"id": mid[:120], "name": str(row.get("name") or mid)[:120],
                          "kind": "speech" if "whisper" in mid.lower() else "chat",
                          "free": bool(free) if provider == "openrouter" else True})
    return sorted(items, key=lambda r: r["id"])[:400]
