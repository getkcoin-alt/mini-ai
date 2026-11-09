"""Mini AI Realtime Voice Pipeline (mini.realtime.v1)

Modular streaming architecture on NFC private VM:
- Framing & Silero VAD (16kHz PCM16 LE, 20ms = 320 samples)
- Streaming STT via faster-whisper (tiny.en, int8 on CPU)
- Streaming LLM via local Ollama (MINI_OLLAMA_MODEL, kept warm)
- Clause-streamed TTS in Mini's one voice (Chatterbox, conditioning cached)
- Binary PCM16 24kHz downlink [0x02][uint32 LE stream_id][payload]
- Genuine barge-in interruption & playback truncation
- Supabase JWT authentication gate
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import struct
import time
import uuid
from typing import AsyncGenerator

import httpx
import numpy as np
import torch
from fastapi import WebSocket, WebSocketDisconnect

from . import engine, memory, resource_limits, ws_auth

logger = logging.getLogger("mini.realtime")

MINI_REALTIME_PROTOCOL = "mini.realtime.v1"
INPUT_RATE = 16000
OUTPUT_RATE = 24000
FRAME_MS = 20
FRAME_SAMPLES = int(INPUT_RATE * FRAME_MS / 1000)  # 320
FRAME_BYTES = FRAME_SAMPLES * 2                   # 640 bytes PCM16
MAX_OUTPUT_CHUNK_BYTES = 3840                     # 80ms PCM16 24kHz

_SILERO_MODEL = None
_SILERO_LOCK = asyncio.Lock()


async def get_silero_vad():
    global _SILERO_MODEL
    if _SILERO_MODEL is None:
        async with _SILERO_LOCK:
            if _SILERO_MODEL is None:
                # Load silero vad ONNX model
                model, _ = torch.hub.load(
                    "snakers4/silero-vad", "silero_vad", onnx=True, trust_repo=True
                )
                _SILERO_MODEL = model
                logger.info("Silero VAD ONNX loaded for realtime pipeline")
    return _SILERO_MODEL


async def verify_supabase_token(access_token: str) -> dict | None:
    """Validate Supabase access token via Supabase Auth API."""
    if not access_token or not isinstance(access_token, str):
        return None
    supabase_url = os.environ.get(
        "MINI_SUPABASE_URL", "https://gkdaxtnlwojggdqitsex.supabase.co"
    ).rstrip("/")
    publishable_key = os.environ.get("MINI_SUPABASE_PUBLISHABLE_KEY", "")

    headers = {"Authorization": f"Bearer {access_token}"}
    if publishable_key:
        headers["apikey"] = publishable_key

    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(f"{supabase_url}/auth/v1/user", headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                if data and isinstance(data, dict) and "id" in data:
                    return data
    except Exception as exc:
        logger.warning("Supabase auth verification request error: %s", exc)
    return None


FIRST_CLAUSE_MIN_CHARS = 12
FIRST_CLAUSE_MAX_WORDS = 7


def split_clause(buffer: str, *, first: bool) -> tuple[str, str] | None:
    """Return (clause_to_speak, remainder) once `buffer` holds a speakable clause.

    Sentence ends (. ! ?) always cut. The first clause also cuts at a comma
    or after a few words so speech starts sooner; later clauses cut at a
    comma only when long, to keep prosody natural.
    """
    for i, ch in enumerate(buffer):
        if ch in ".!?\n" and i + 1 < len(buffer) and buffer[i + 1] in " \n\"')":
            clause = buffer[:i + 1].strip()
            if clause:
                return clause, buffer[i + 1:]
        if ch in ",;:" and (len(buffer[:i]) >= (FIRST_CLAUSE_MIN_CHARS if first else 60)):
            if i + 1 < len(buffer):
                return buffer[:i + 1].strip(), buffer[i + 1:]
    if first:
        words = buffer.split(" ")
        if len(words) > FIRST_CLAUSE_MAX_WORDS + 1 and len(buffer) >= FIRST_CLAUSE_MIN_CHARS:
            head = " ".join(words[:FIRST_CLAUSE_MAX_WORDS])
            return head.strip(), buffer[len(head):]
    return None


class SileroVADDetector:
    def __init__(self, model):
        self.model = model
        self.buffer = []
        self.is_speech_active = False
        self.speech_frames = 0
        self.silence_frames = 0
        self.speech_threshold = 0.5
        self.min_speech_frames = 3    # 60ms to trigger speech_started
        self.min_silence_frames = 25  # 500ms to trigger speech_ended
        self.utterance_samples = []

    def feed(self, pcm_bytes: bytes) -> tuple[str | None, float]:
        """Feed 20ms PCM16 LE frame (320 samples). Returns (event_type, prob)."""
        samples = (
            np.frombuffer(pcm_bytes, dtype="<i2").astype(np.float32) / 32768.0
        )
        self.buffer.extend(samples.tolist())
        self.utterance_samples.extend(samples.tolist())

        event = None
        prob = 0.0

        # Silero VAD requires chunks of 512 samples at 16kHz
        if len(self.buffer) >= 512:
            chunk = torch.tensor(self.buffer[:512], dtype=torch.float32)
            self.buffer = self.buffer[320:]  # step forward by 20ms
            prob = self.model(chunk, INPUT_RATE).item()

            if prob >= self.speech_threshold:
                self.speech_frames += 1
                self.silence_frames = 0
                if (
                    not self.is_speech_active
                    and self.speech_frames >= self.min_speech_frames
                ):
                    self.is_speech_active = True
                    event = "speech_started"
            else:
                self.silence_frames += 1
                if (
                    self.is_speech_active
                    and self.silence_frames >= self.min_silence_frames
                ):
                    self.is_speech_active = False
                    self.speech_frames = 0
                    event = "speech_ended"

        return event, prob

    def get_and_reset_utterance(self) -> np.ndarray:
        samples = np.array(self.utterance_samples, dtype=np.float32)
        self.utterance_samples = []
        self.speech_frames = 0
        self.silence_frames = 0
        self.is_speech_active = False
        return samples


class MiniRealtimeSession:
    def __init__(self, websocket: WebSocket, allow_local_dev_token: bool = False, require_ticket: bool = False):
        self.ws = websocket
        self.allow_local_dev_token = allow_local_dev_token
        self.require_ticket = require_ticket
        self.session_id = f"sess_{uuid.uuid4().hex[:12]}"
        self.user_id: str | None = None
        self.mode = "friend"
        self.is_ready = False
        self.closed = False
        self.vad_detector: SileroVADDetector | None = None

        self.current_response_id: str | None = None
        self.current_stream_id = 0
        self.response_task: asyncio.Task | None = None
        self.cancelled_response_ids = set()
        self.last_played_ms = 0
        self.conversation_history: list[dict] = []

    def owner_profile_facts(self) -> list[str]:
        """Profile facts allowed in this session's prompt.

        The SQLite profile is the single-owner pilot store, not per-account
        memory. It is used ONLY for the loopback owner session; verified
        Supabase accounts get no shared profile until per-user, RLS-scoped
        memory is wired to the worker.
        """
        if self.user_id != "local-dev-owner":
            return []
        profile_data = memory.get_profile()
        if not (profile_data.get("saved") and profile_data.get("profile")):
            return []
        return [f"{k}: {v}" for k, v in profile_data["profile"].items() if v]

    async def send_json(self, data: dict):
        if not self.closed:
            try:
                await self.ws.send_text(json.dumps(data))
            except Exception as exc:
                logger.debug("Error sending json: %s", exc)

    async def send_audio_chunk(self, stream_id: int, pcm_chunk: bytes):
        if not self.closed:
            # Wire protocol: [0x02][uint32 LE stream_id][PCM16 bytes]
            header = struct.pack("<BI", 2, stream_id)
            try:
                await self.ws.send_bytes(header + pcm_chunk)
            except Exception as exc:
                logger.debug("Error sending audio chunk: %s", exc)

    async def handle_connection(self):
        await self.ws.accept()
        vad_model = await get_silero_vad()
        self.vad_detector = SileroVADDetector(vad_model)

        try:
            while not self.closed:
                message = await self.ws.receive()
                if message.get("type") == "websocket.disconnect":
                    break

                if "text" in message and message["text"]:
                    await self.handle_text_event(message["text"])
                elif "bytes" in message and message["bytes"]:
                    await self.handle_audio_frame(message["bytes"])
        except WebSocketDisconnect:
            logger.info("Realtime session disconnected: %s", self.session_id)
        except Exception as exc:
            logger.error("Realtime session error: %s", exc, exc_info=True)
            await self.send_json({"type": "session.error", "message": str(exc)})
        finally:
            self.cleanup()

    async def handle_text_event(self, text_data: str):
        try:
            event = json.loads(text_data)
        except Exception:
            await self.send_json({"type": "session.error", "message": "Invalid JSON format"})
            return

        event_type = event.get("type")

        if event_type == "session.start":
            if event.get("protocol") != MINI_REALTIME_PROTOCOL:
                await self.send_json({"type": "session.error", "message": "Unsupported protocol version"})
                await self.ws.close(code=1002, reason="Unsupported protocol")
                return

            access_token = event.get("access_token")
            ticket_user = ws_auth.verify_realtime_ticket(event.get("ticket")) if self.require_ticket else None
            if self.require_ticket and not ticket_user:
                user = None
            else:
                user = (ws_auth.local_dev_identity(access_token, self.allow_local_dev_token)
                        or await verify_supabase_token(access_token))
            if user and self.require_ticket and user.get("id") != ticket_user:
                user = None
            if not user or not user.get("id"):
                await self.send_json({"type": "session.error", "message": "Authentication failed: invalid or expired token"})
                await self.ws.close(code=4401, reason="Unauthorized")
                return

            self.user_id = user["id"]
            self.mode = "mentor" if event.get("mode") == "mentor" else "friend"
            self.is_ready = True
            await self.send_json({"type": "session.ready"})
            logger.info("Session ready for user %s in %s mode", self.user_id, self.mode)

        elif event_type == "playback.progress":
            resp_id = event.get("response_id")
            if resp_id == self.current_response_id:
                self.last_played_ms = max(self.last_played_ms, int(event.get("heard_ms", 0)))

        elif event_type == "response.cancel":
            resp_id = event.get("response_id")
            heard_ms = int(event.get("heard_ms", 0))
            await self.interrupt_response(resp_id, heard_ms, reason=event.get("reason", "user_cancel"))

        elif event_type == "session.end":
            self.cleanup()
            await self.ws.close(code=1000, reason="Session ended by client")

    async def handle_audio_frame(self, frame_bytes: bytes):
        if not self.is_ready or self.closed:
            return

        if len(frame_bytes) != FRAME_BYTES:
            logger.debug("Received audio frame of unexpected length: %d", len(frame_bytes))
            return

        event, prob = self.vad_detector.feed(frame_bytes)

        if event == "speech_started":
            logger.info("VAD speech_started (prob=%.3f)", prob)
            await self.send_json({"type": "input.vad.speech_started"})

            # Genuine barge-in: If Mini is speaking or thinking, cancel immediately!
            if self.current_response_id:
                logger.info("Barge-in triggered by user speech!")
                await self.interrupt_response(self.current_response_id, self.last_played_ms, reason="barge-in")

        elif event == "speech_ended":
            logger.info("VAD speech_ended")
            await self.send_json({"type": "input.vad.speech_ended"})

            utterance_samples = self.vad_detector.get_and_reset_utterance()
            # Need at least 0.35s of speech to transcribe
            if len(utterance_samples) >= int(INPUT_RATE * 0.35):
                asyncio.create_task(self.process_user_utterance(utterance_samples))

    async def interrupt_response(self, response_id: str | None, heard_ms: int, reason: str = "barge-in"):
        if not response_id or response_id in self.cancelled_response_ids:
            return

        self.cancelled_response_ids.add(response_id)
        if self.response_task and not self.response_task.done():
            self.response_task.cancel()

        logger.info("Interrupted response %s at %d ms (reason=%s)", response_id, heard_ms, reason)
        await self.send_json({"type": "response.cancelled", "response_id": response_id})

        self.current_response_id = None
        self.last_played_ms = 0

    async def process_user_utterance(self, audio_samples: np.ndarray):
        # 1. Transcribe via faster-whisper on thread pool
        t0 = time.perf_counter()
        loop = asyncio.get_running_loop()

        def _do_stt():
            with engine.MODEL_LOCK:
                model = engine._WHISPER
                if model is None:
                    # Initialize whisper model
                    from faster_whisper import WhisperModel
                    hardware = "cuda" if torch.cuda.is_available() else "cpu"
                    model = WhisperModel(
                        os.environ.get("MINI_WHISPER_MODEL", "tiny.en"),
                        device=hardware,
                        compute_type="float16" if hardware == "cuda" else "int8",
                        cpu_threads=int(os.environ.get("MINI_CPU_THREADS", "6")),
                        num_workers=1,
                    )
                    engine._WHISPER = model

                segments, _ = model.transcribe(audio_samples, beam_size=1, vad_filter=False)
                return " ".join(seg.text.strip() for seg in segments).strip()

        transcript = await loop.run_in_executor(None, _do_stt)
        stt_ms = (time.perf_counter() - t0) * 1000
        logger.info("STT final: '%s' in %.1f ms", transcript, stt_ms)

        if not transcript or len(transcript) < 2:
            return

        await self.send_json({"type": "input.transcript.final", "text": transcript})

        # Launch response generation task
        self.response_task = asyncio.create_task(self.generate_and_stream_response(transcript))

    async def generate_and_stream_response(self, user_transcript: str):
        response_id = f"resp_{uuid.uuid4().hex[:12]}"
        self.current_response_id = response_id
        self.last_played_ms = 0

        await self.send_json({"type": "response.started", "response_id": response_id})

        # Reserve inference slot safely
        try:
            with resource_limits.reserve_inference(model_loaded=True):
                await self._run_llm_and_tts(response_id, user_transcript)
        except resource_limits.VoiceBusy:
            logger.warning("Voice worker busy; rejecting turn")
            await self.send_json({
                "type": "session.error",
                "message": "Mini is completing another voice turn. Try again shortly.",
            })
        except resource_limits.VoiceMemoryLow as exc:
            logger.warning("Voice memory low: %s", exc)
            await self.send_json({
                "type": "session.error",
                "message": "Insufficient server RAM for voice generation.",
            })
        except asyncio.CancelledError:
            logger.info("Response task cancelled during execution")
        except Exception as exc:
            logger.error("Error generating response: %s", exc, exc_info=True)
            await self.send_json({"type": "session.error", "message": f"Generation failed: {str(exc)}"})
        finally:
            if self.current_response_id == response_id:
                self.current_response_id = None

    async def _run_llm_and_tts(self, response_id: str, user_transcript: str):
        """Stream LLM text into a clause queue while a separate task voices it.

        The LLM never waits for speech synthesis. The first clause is cut
        short (first comma or ~6 words) so Mini starts talking as early as
        possible; later clauses follow sentence boundaries. All clauses of one
        reply share ONE response.audio.start / response.audio.end pair so the
        browser does not flush already-buffered speech between sentences.
        """
        t_start = time.perf_counter()
        system_prompt = engine.PROMPTS.get(self.mode, engine.PROMPTS["friend"])
        details = self.owner_profile_facts()
        if details:
            system_prompt += "\nUser profile facts:\n" + "\n".join(details)
        messages = [
            {"role": "system", "content": system_prompt},
            *self.conversation_history[-6:],
            {"role": "user", "content": user_transcript},
        ]
        ollama_url = (os.environ.get("MINI_OLLAMA_URL") or "http://127.0.0.1:11434").rstrip("/")
        self.current_stream_id += 1
        stream_id = self.current_stream_id
        clauses: asyncio.Queue = asyncio.Queue()
        timing = {"llm_first_token_ms": None, "first_audio_ms": None}
        speaker = asyncio.create_task(self._speak_clauses(response_id, stream_id, clauses, timing, t_start))

        full_reply: list[str] = []
        buffer = ""
        clauses_sent = 0
        try:
            async with httpx.AsyncClient(timeout=60.0, trust_env=False) as client:
                async with client.stream("POST", f"{ollama_url}/api/chat", json={
                    "model": os.environ.get("MINI_OLLAMA_MODEL", "llama3.2:1b"),
                    "messages": messages,
                    "stream": True,
                    "keep_alive": os.environ.get("MINI_OLLAMA_KEEP_ALIVE", "30m"),
                    "options": {"num_predict": 100, "temperature": 0.6, "num_ctx": 2048,
                                "num_thread": engine.llm_threads()},
                }) as stream_resp:
                    async for line in stream_resp.aiter_lines():
                        if response_id in self.cancelled_response_ids:
                            return
                        if not line:
                            continue
                        try:
                            chunk_json = json.loads(line)
                        except Exception:
                            continue
                        delta = chunk_json.get("message", {}).get("content", "")
                        if delta:
                            if timing["llm_first_token_ms"] is None:
                                timing["llm_first_token_ms"] = round((time.perf_counter() - t_start) * 1000)
                            full_reply.append(delta)
                            buffer += delta
                            await self.send_json({"type": "response.text.delta", "response_id": response_id, "text": delta})
                            cut = split_clause(buffer, first=clauses_sent == 0)
                            if cut:
                                clause, buffer = cut
                                clauses.put_nowait(clause)
                                clauses_sent += 1
                        if chunk_json.get("done", False):
                            break
            if buffer.strip() and response_id not in self.cancelled_response_ids:
                clauses.put_nowait(buffer.strip())
        finally:
            clauses.put_nowait(None)
            if response_id in self.cancelled_response_ids:
                speaker.cancel()
            try:
                await speaker
            except asyncio.CancelledError:
                pass

        if response_id not in self.cancelled_response_ids:
            complete_text = "".join(full_reply).strip()
            self.conversation_history.append({"role": "user", "content": user_transcript})
            self.conversation_history.append({"role": "assistant", "content": complete_text})
            total_ms = round((time.perf_counter() - t_start) * 1000)
            await self.send_json({"type": "pipeline.timing", "response_id": response_id, **timing, "total_ms": total_ms})
            await self.send_json({"type": "response.finished", "response_id": response_id})
            logger.info("Response %s: llm_first=%sms first_audio=%sms total=%sms '%s'", response_id,
                        timing["llm_first_token_ms"], timing["first_audio_ms"], total_ms, complete_text)

    async def _speak_clauses(self, response_id: str, stream_id: int, clauses: asyncio.Queue,
                             timing: dict, t_start: float):
        loop = asyncio.get_running_loop()
        started = False
        while True:
            clause = await clauses.get()
            if clause is None or response_id in self.cancelled_response_ids:
                break
            samples, _rate = await loop.run_in_executor(None, engine.synthesize_samples, clause[:300], "en")
            if response_id in self.cancelled_response_ids:
                break
            pcm_bytes = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()
            if not started:
                started = True
                timing["first_audio_ms"] = round((time.perf_counter() - t_start) * 1000)
                await self.send_json({"type": "response.audio.start", "response_id": response_id, "stream_id": stream_id})
            for offset in range(0, len(pcm_bytes), MAX_OUTPUT_CHUNK_BYTES):
                if response_id in self.cancelled_response_ids:
                    return
                await self.send_audio_chunk(stream_id, pcm_bytes[offset:offset + MAX_OUTPUT_CHUNK_BYTES])
        if started and response_id not in self.cancelled_response_ids:
            await self.send_json({"type": "response.audio.end", "response_id": response_id})

    def cleanup(self):
        self.closed = True
        if self.response_task and not self.response_task.done():
            self.response_task.cancel()
        self.is_ready = False
