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
from datetime import datetime, timezone
from typing import AsyncGenerator

import httpx
import numpy as np
import torch
from fastapi import WebSocket, WebSocketDisconnect

from . import admission, engine, memory, mind, resource_limits, ws_auth

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


def _private(text: str) -> str:
    """What users say and what Mini replies never goes to the server log in
    production; only its length. MINI_LOG_TRANSCRIPTS=1 is for local debugging."""
    if os.environ.get("MINI_LOG_TRANSCRIPTS") == "1":
        return repr(text)
    return f"[{len(text or '')} chars]"


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


async def fetch_user_context(access_token: str, user_id: str) -> list[str]:
    """This user's own profile and memories, read with THEIR token (RLS)."""
    supabase_url = os.environ.get("MINI_SUPABASE_URL", "https://gkdaxtnlwojggdqitsex.supabase.co").rstrip("/")
    key = os.environ.get("MINI_SUPABASE_PUBLISHABLE_KEY", "")
    if not key or not access_token:
        return []
    headers = {"Authorization": f"Bearer {access_token}", "apikey": key}
    facts: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
            prof = await client.get(f"{supabase_url}/rest/v1/mini_profiles", headers=headers, params={
                "select": "display_name,mini_name,companion_mode,tone,focus,boundaries",
                "user_id": f"eq.{user_id}", "limit": "1"})
            mems = await client.get(f"{supabase_url}/rest/v1/mini_memories", headers=headers, params={
                "select": "kind,content", "user_id": f"eq.{user_id}",
                "or": "(expires_at.is.null,expires_at.gt.now())",
                "order": "updated_at.desc", "limit": "20"})
        if prof.status_code == 200 and prof.json():
            row = prof.json()[0]
            labels = {"display_name": "Call the user", "mini_name": "Your name is", "companion_mode": "Preferred mode",
                      "tone": "Preferred tone", "focus": "Current focus", "boundaries": "Boundaries to respect"}
            facts += [f"{labels[k]}: {str(v)[:300]}" for k, v in row.items() if k in labels and v]
        if mems.status_code == 200:
            facts += [f"{m.get('kind', 'fact')}: {str(m.get('content', ''))[:300]}" for m in mems.json() if m.get("content")]
    except Exception as exc:
        logger.warning("Could not load user context: %s", type(exc).__name__)
    return facts[:30]


_LEARNING_TASKS: set = set()


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
        self.unanswered_transcript = ""
        self.reply_audio_started = False
        self.client_ip = ""
        self.profile_facts: list[str] = []
        self.admission_task: asyncio.Task | None = None
        self.watchdog_task: asyncio.Task | None = None
        self.holds_floor = False
        self.ready_at: float | None = None
        self.last_activity = time.monotonic()
        self.usage_recorded = False
        self.mind_pkg: dict | None = None
        self.mind_client: mind.MindClient | None = None
        self.started_wall: datetime | None = None

    def owner_profile_facts(self) -> list[str]:
        """Facts allowed in this session's prompt.

        Supabase accounts get ONLY their own profile and memories (loaded at
        session.start with their token, so row-level security applies). The
        SQLite single-owner profile is used only for the loopback dev session.
        """
        if self.user_id != "local-dev-owner":
            return list(self.profile_facts)
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

            if self.user_id or self.admission_task:
                return  # session.start only once per connection
            self.user_id = user["id"]
            self.mode = "mentor" if event.get("mode") == "mentor" else "friend"
            if not await self.check_limits():
                return
            if self.user_id == "local-dev-owner" and os.environ.get("MINI_DEV_MIND_PACKAGE"):
                # loopback test sessions only: a sample mind package from a file (never learns)
                try:
                    with open(os.environ["MINI_DEV_MIND_PACKAGE"], encoding="utf-8") as fh:
                        self.mind_pkg = json.load(fh)
                except (OSError, ValueError) as exc:
                    logger.warning("dev mind package unreadable: %s", exc)
            if self.user_id != "local-dev-owner":
                self.mind_client = mind.MindClient(access_token, self.user_id)
                self.mind_pkg = await self.mind_client.load_package()
                if not (self.mind_pkg or {}).get("known"):
                    # mind not available yet: fall back to the plain profile
                    self.profile_facts = await fetch_user_context(access_token, self.user_id)
            self.admission_task = asyncio.create_task(self.wait_for_floor())

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

    async def end_session(self, reason: str, message: str, code: int = 1000):
        await self.send_json({"type": "session.ending", "reason": reason, "message": message})
        self.cleanup()
        try:
            await self.ws.close(code=code, reason=reason[:60])
        except Exception:
            pass

    async def check_limits(self) -> bool:
        """Start-rate and daily allowance; the dev loopback owner is exempt."""
        if self.user_id == "local-dev-owner":
            return True
        if not admission.STARTS.allow(self.user_id, limit=6, window_s=60):
            await self.end_session("rate_limited", "Too many attempts. Please wait a minute and try again.", 4429)
            return False
        if admission.USAGE.remaining(self.user_id) < 15:
            minutes = admission.daily_seconds() // 60
            await self.end_session("daily_limit", f"You've used today's {minutes} minutes with Mini. "
                                   "Come back tomorrow!", 4429)
            return False
        return True

    async def wait_for_floor(self):
        async def report(position: int):
            await self.send_json({"type": "session.queued", "position": position,
                                  "message": "Mini is talking with someone else. You're next in line."
                                  if position == 1 else f"Mini is busy. You're number {position} in line."})
        try:
            if not await admission.FLOOR.acquire(self.session_id, report):
                await self.end_session("queue_full", "Mini is very busy right now. Please try again in a few minutes.", 4429)
                return
            self.holds_floor = True
            if self.closed:
                admission.FLOOR.release(self.session_id)
                return
            self.ready_at = time.monotonic()
            self.last_activity = self.ready_at
            self.is_ready = True
            limits = {"max_seconds": admission.max_session_seconds(), "idle_seconds": admission.idle_seconds()}
            if self.user_id != "local-dev-owner":
                limits["remaining_today_seconds"] = int(admission.USAGE.remaining(self.user_id))
            sync = (self.mind_pkg or {}).get("sync") or {}
            await self.send_json({"type": "session.ready", "limits": limits,
                                  "sync": {"score": sync.get("score")} if sync else None})
            self.started_wall = datetime.now(timezone.utc)
            self.watchdog_task = asyncio.create_task(self.watchdog())
            if (self.mind_pkg or {}).get("known") and os.environ.get("MINI_SPEAK_FIRST", "1") == "1":
                # Like a friend who missed them: Mini opens the conversation.
                self.response_task = asyncio.create_task(
                    self.generate_and_stream_response(mind.opening_instruction(self.mind_pkg), opening=True))
            logger.info("Session %s ready in %s mode (queue now %d)", self.session_id, self.mode,
                        admission.FLOOR.waiting)
        except asyncio.CancelledError:
            pass

    def busy_speaking(self) -> bool:
        return bool(self.current_response_id) or bool(self.vad_detector and self.vad_detector.is_speech_active)

    async def watchdog(self):
        try:
            while not self.closed:
                await asyncio.sleep(1)
                now = time.monotonic()
                if self.busy_speaking():
                    self.last_activity = now
                elapsed = now - (self.ready_at or now)
                if elapsed >= admission.max_session_seconds():
                    await self.end_session("time_limit", "That's our time for this conversation. Start a new one anytime!")
                    return
                if now - self.last_activity >= admission.idle_seconds():
                    await self.end_session("idle", "I'll hang up for now since it's quiet. Tap to talk again anytime.")
                    return
                if (self.user_id != "local-dev-owner"
                        and elapsed >= admission.USAGE.remaining(self.user_id)):
                    await self.end_session("daily_limit", "You've used today's time with Mini. Come back tomorrow!")
                    return
        except asyncio.CancelledError:
            pass

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
        logger.info("STT final: %s in %.1f ms", _private(transcript), stt_ms)

        if not transcript or len(transcript) < 2:
            return

        # The user kept talking before Mini said anything: drop that pending
        # answer and reply to the whole thing once (a mid-sentence pause must
        # not create two competing turns).
        previous = self.response_task
        if previous and not previous.done():
            if self.unanswered_transcript and not self.reply_audio_started:
                transcript = (self.unanswered_transcript + " " + transcript).strip()
            if self.current_response_id:
                await self.interrupt_response(self.current_response_id, self.last_played_ms, reason="user_continued")
            previous.cancel()
            try:
                await asyncio.wait_for(asyncio.gather(previous, return_exceptions=True), 15)
            except asyncio.TimeoutError:
                logger.warning("Previous response did not stop within 15 s")

        await self.send_json({"type": "input.transcript.final", "text": transcript})
        self.unanswered_transcript = transcript
        self.reply_audio_started = False
        self.response_task = asyncio.create_task(self.generate_and_stream_response(transcript))

    async def generate_and_stream_response(self, user_transcript: str, opening: bool = False):
        response_id = f"resp_{uuid.uuid4().hex[:12]}"
        self.current_response_id = response_id
        self.last_played_ms = 0

        await self.send_json({"type": "response.started", "response_id": response_id})

        # Wait (briefly) for the single inference slot instead of failing the
        # whole live session: another HTTP turn or a just-cancelled clause may
        # still be finishing.
        try:
            deadline = time.monotonic() + 30
            while True:
                try:
                    slot = resource_limits.reserve_inference(model_loaded=True)
                    slot.__enter__()
                    break
                except resource_limits.VoiceBusy:
                    if time.monotonic() > deadline or response_id in self.cancelled_response_ids:
                        raise
                    await asyncio.sleep(0.2)
            try:
                await self._run_llm_and_tts(response_id, user_transcript, opening=opening)
            finally:
                slot.__exit__(None, None, None)
        except resource_limits.VoiceBusy:
            logger.warning("Voice worker busy for 30 s; skipping this turn")
            await self.send_json({"type": "pipeline.busy", "response_id": response_id,
                                  "message": "Mini is still finishing something. Please say that again."})
            await self.send_json({"type": "response.cancelled", "response_id": response_id})
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

    async def _run_llm_and_tts(self, response_id: str, user_transcript: str, opening: bool = False):
        """Stream LLM text into a clause queue while a separate task voices it.

        The LLM never waits for speech synthesis. The first clause is cut
        short (first comma or ~6 words) so Mini starts talking as early as
        possible; later clauses follow sentence boundaries. All clauses of one
        reply share ONE response.audio.start / response.audio.end pair so the
        browser does not flush already-buffered speech between sentences.
        """
        t_start = time.perf_counter()
        system_prompt = engine.PROMPTS.get(self.mode, engine.PROMPTS["friend"])
        mind_block = mind.render_prompt(self.mind_pkg)
        if mind_block:
            system_prompt += "\n" + mind_block
        else:
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
                    "keep_alive": engine.ollama_keep_alive(),
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
            extra = engine.crisis_followup(user_transcript, "".join(full_reply))
            if extra and response_id not in self.cancelled_response_ids:
                full_reply.append(" " + extra)
                await self.send_json({"type": "response.text.delta", "response_id": response_id, "text": " " + extra})
                clauses.put_nowait(extra)
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
            if not opening:
                self.conversation_history.append({"role": "user", "content": user_transcript})
            self.conversation_history.append({"role": "assistant", "content": complete_text})
            total_ms = round((time.perf_counter() - t_start) * 1000)
            await self.send_json({"type": "pipeline.timing", "response_id": response_id, **timing, "total_ms": total_ms})
            await self.send_json({"type": "response.finished", "response_id": response_id})
            logger.info("Response %s: llm_first=%sms first_audio=%sms total=%sms %s", response_id,
                        timing["llm_first_token_ms"], timing["first_audio_ms"], total_ms, _private(complete_text))

    async def _speak_clauses(self, response_id: str, stream_id: int, clauses: asyncio.Queue,
                             timing: dict, t_start: float):
        loop = asyncio.get_running_loop()
        started = False
        while True:
            clause = await clauses.get()
            if clause is None or response_id in self.cancelled_response_ids:
                break
            t_clause = time.perf_counter()
            audio_s = 0.0
            async for samples in self._clause_audio(clause[:300], response_id):
                if response_id in self.cancelled_response_ids:
                    return
                audio_s += len(samples) / OUTPUT_RATE
                pcm_bytes = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()
                if not started:
                    started = True
                    self.reply_audio_started = True
                    timing["first_audio_ms"] = round((time.perf_counter() - t_start) * 1000)
                    await self.send_json({"type": "response.audio.start", "response_id": response_id, "stream_id": stream_id})
                for offset in range(0, len(pcm_bytes), MAX_OUTPUT_CHUNK_BYTES):
                    if response_id in self.cancelled_response_ids:
                        return
                    await self.send_audio_chunk(stream_id, pcm_bytes[offset:offset + MAX_OUTPUT_CHUNK_BYTES])
            logger.info("TTS clause %.0f ms for %.1f s audio (queued at +%.0f ms): %s",
                        (time.perf_counter() - t_clause) * 1000, audio_s, (t_clause - t_start) * 1000, _private(clause))
        if started and response_id not in self.cancelled_response_ids:
            await self.send_json({"type": "response.audio.end", "response_id": response_id})

    async def _clause_audio(self, clause: str, response_id: str):
        """Yield float32 24 kHz chunks for one clause in Mini's voice.

        With MINI_STREAMING_TTS=1 audio streams while the clause is
        still being generated (see streaming_tts); otherwise the whole clause
        is synthesized first.
        """
        loop = asyncio.get_running_loop()
        if os.environ.get("MINI_STREAMING_TTS", "0") != "1":
            samples, _rate = await loop.run_in_executor(None, engine.synthesize_samples, clause, "en")
            yield samples
            return
        from . import streaming_tts
        chunks: asyncio.Queue = asyncio.Queue()
        stopped = {"value": False}

        def cancelled() -> bool:
            return stopped["value"] or self.closed or response_id in self.cancelled_response_ids

        def produce():
            try:
                with engine.MODEL_LOCK:
                    model = engine._conditioned_tts("en")
                    for chunk in streaming_tts.stream_speech(model, clause, cancelled=cancelled):
                        loop.call_soon_threadsafe(chunks.put_nowait, chunk)
            except BaseException as exc:  # handed to the event loop below
                loop.call_soon_threadsafe(chunks.put_nowait, exc)
            finally:
                loop.call_soon_threadsafe(chunks.put_nowait, None)

        worker = loop.run_in_executor(None, produce)
        try:
            while True:
                item = await chunks.get()
                if item is None:
                    break
                if isinstance(item, BaseException):
                    raise item
                yield item
        finally:
            stopped["value"] = True
            await asyncio.shield(worker)

    def cleanup(self):
        if self.admission_task and not self.admission_task.done():
            self.admission_task.cancel()
        if self.watchdog_task and not self.watchdog_task.done() and self.watchdog_task is not asyncio.current_task():
            self.watchdog_task.cancel()
        if self.holds_floor:
            self.holds_floor = False
            admission.FLOOR.release(self.session_id)
        if self.ready_at and not self.usage_recorded and self.user_id and self.user_id != "local-dev-owner":
            self.usage_recorded = True
            try:
                admission.USAGE.add(self.user_id, time.monotonic() - self.ready_at)
            except Exception as exc:
                logger.warning("Could not record usage: %s", exc)
        already_closed = self.closed
        self.closed = True
        if self.response_task and not self.response_task.done():
            self.response_task.cancel()
        self.is_ready = False
        if not already_closed:
            self.schedule_learning()

    def schedule_learning(self):
        """After the conversation, Mini looks back and learns (in the background)."""
        turns = sum(1 for t in self.conversation_history if t["role"] == "user")
        if (not self.mind_client or not self.started_wall or turns == 0
                or os.environ.get("MINI_MIND_LEARN", "1") != "1"):
            return
        history, pkg, started = list(self.conversation_history), self.mind_pkg, self.started_wall
        client, sid = self.mind_client, self.session_id
        self.conversation_history = []   # the transcript is never kept beyond this

        async def learn():
            ended = datetime.now(timezone.utc)
            try:
                # Learn only while nobody is talking to Mini, without holding the voice
                # slot, so a new conversation is never blocked by background learning.
                deadline = time.monotonic() + 1800
                while admission.FLOOR.holder is not None or resource_limits.busy():
                    if time.monotonic() > deadline:
                        logger.warning("mind: learning skipped for %s (Mini busy for 30 min)", sid)
                        return
                    await asyncio.sleep(3)
                learned = await mind.extract(history, threads=int(os.environ.get("MINI_MIND_THREADS") or 8),
                                             keep_alive=engine.ollama_keep_alive())
                counts = await client.learn(learned, pkg, started, ended, turns)
                logger.info("mind: learned after %s: %s", sid, counts)
            except Exception as exc:
                logger.warning("mind: learning failed for %s: %s", sid, str(exc)[:200])

        task = asyncio.get_running_loop().create_task(learn())
        _LEARNING_TASKS.add(task)
        task.add_done_callback(_LEARNING_TASKS.discard)
