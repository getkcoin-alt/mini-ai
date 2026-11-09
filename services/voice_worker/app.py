"""Private Mini AI voice worker.

Serve ONLY 127.0.0.1 locally. For remote mobile access, put behind an HTTPS
private tunnel and require a strong MINI_WORKER_TOKEN. The Vercel gateway
verifies owner Google identity before forwarding voice samples or transcripts.

Public /v1 routes always require a token. /api/voice aliases are intentionally
available only to the locally served frontend on loopback.
"""
from __future__ import annotations

import base64
import binascii
import os
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import engine, memory, resource_limits, ws_auth

logger = logging.getLogger("mini.voice")
# uvicorn leaves the root logger at WARNING; keep Mini's own INFO lines
# (per-turn latency, clause timing) visible in journald.
_mini_log = logging.getLogger("mini")
if not _mini_log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s: %(message)s"))
    _mini_log.addHandler(_handler)
    _mini_log.setLevel(logging.INFO)
    _mini_log.propagate = False


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Optional; only enable after measuring sufficient RAM on this shared VPS.
    if os.environ.get("MINI_PRELOAD_TTS", "0") == "1" and engine.reference_for("friend"):
        try:
            with resource_limits.reserve_inference(model_loaded=False):
                with engine.MODEL_LOCK:
                    engine._conditioned_tts("en")
            logger.info("Chatterbox loaded and conditioned on Mini's voice once")
        except (resource_limits.VoiceMemoryLow, resource_limits.VoiceBusy, Exception) as exc:
            logger.warning("Optional voice prewarm unavailable; running cold: %s", exc)
    yield


app = FastAPI(title="Mini AI Private Voice Worker", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
MAX_BASE64_LENGTH = 4_100_000


@app.middleware("http")
async def refuse_browser_origins(request: Request, call_next):
    # Public worker domain is server-to-server only (see ws_auth). Runs before
    # body parsing and token checks, so preflights and browser calls get 403.
    if ws_auth.browser_origin_refused(request.url.path, request.headers.get("origin")):
        return JSONResponse(status_code=403, content={"detail": "Browser origins are not allowed on /v1."})
    return await call_next(request)


class AudioUpload(BaseModel):
    audio_base64: str = Field(min_length=1, max_length=MAX_BASE64_LENGTH)
    mime: str = Field(default="audio/wav", max_length=70)
    consent: bool = False
    mode: str = Field(default="friend", pattern="^(friend|mentor)$")


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=700)
    language: str = Field(default="en", pattern="^(en|hi)$")
    mode: str = Field(default="friend", pattern="^(friend|mentor)$")


class ChatRequest(SpeechRequest):
    mode: str = Field(default="friend", pattern="^(friend|mentor)$")


class ProfileSaveRequest(BaseModel):
    profile: dict[str, str]
    consent: bool = False


class VoiceTurnRequest(BaseModel):
    audio_base64: str = Field(min_length=1, max_length=MAX_BASE64_LENGTH)
    mime: str = Field(default="audio/webm", max_length=70)
    mode: str = Field(default="friend", pattern="^(friend|mentor)$")


def worker_auth(x_mini_worker_token: str | None = Header(default=None)):
    if not ws_auth.worker_token_ok(x_mini_worker_token):
        raise HTTPException(status_code=401, detail="Worker authentication required")


def _local_error(conn) -> str | None:
    # Works for both HTTP Request and WebSocket (both are HTTPConnection).
    return ws_auth.local_connection_error(
        conn.client.host if conn.client else "", conn.url.hostname or "", conn.url.port,
        conn.headers.get("origin"))


def local_auth(request: Request):
    # A reverse-proxy exposing this app publicly would be unsafe: intentionally
    # require direct localhost requests for uncredentialed local UI alias paths.
    error = _local_error(request)
    if error:
        raise HTTPException(status_code=403, detail=error)


def read_audio(value: str) -> bytes:
    try:
        audio = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        raise HTTPException(status_code=400, detail="Invalid base64-encoded audio.")
    if not (1000 <= len(audio) <= 3_000_000):
        raise HTTPException(status_code=413, detail="Audio must be 1KB–3MB.")
    return audio


def safely(run):
    try:
        return run()
    except engine.VoiceNotReady as error:
        raise HTTPException(status_code=503, detail=str(error))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    except Exception:
        # Internal traces are deliberately not sent to the public browser.
        raise HTTPException(status_code=502, detail="Local AI generation failed. Check worker logs.") from None


def wrap_audio(wav: bytes, *, transcript: str = "", reply: str = "", language: str = "en"):
    return {
        "audio_base64": base64.b64encode(wav).decode("ascii"),
        "mime": "audio/wav", "transcript": transcript, "reply": reply,
        "language": language, "provider": "chatterbox-local",
    }


def get_status():
    state = engine.status()
    return {**state, "workerReady": True, "voiceReady": bool(state["referenceReady"]),
            "localStandalone": True, "inferenceBusy": resource_limits.busy(),
            "inferencePolicy": "single-turn-cpu"}


VOICE_LOCKED_DETAIL = "Mini has one fixed voice. Uploading or removing voice samples is disabled."


def receive_sample(data: AudioUpload):
    raise HTTPException(status_code=403, detail=VOICE_LOCKED_DETAIL)


def remove_sample(mode: str = "friend"):
    raise HTTPException(status_code=403, detail=VOICE_LOCKED_DETAIL)


def run_exclusive(work):
    # Acquire before any expensive STT/LLM/TTS operation. No waiting request
    # queue: FastAPI's threadpool must not accumulate heavyweight jobs.
    try:
        with resource_limits.reserve_inference(model_loaded=engine.status()["modelLoaded"]):
            return work()
    except resource_limits.VoiceBusy as exc:
        raise HTTPException(status_code=429, detail=str(exc), headers={"Retry-After": "3"}) from None
    except resource_limits.VoiceMemoryLow as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


def handle_speak(data: SpeechRequest):
    def work():
        wave = safely(lambda: engine.synthesize(data.text, data.language, data.mode))
        return wrap_audio(wave, language=data.language)
    return run_exclusive(work)


def handle_chat(data: ChatRequest):
    if not engine.status()["referenceReady"]:
        raise HTTPException(status_code=409, detail="Upload a voice reference clip first.")

    def work():
        answer = safely(lambda: engine.reply_to(data.text, mode=data.mode, language=data.language,
                                                 profile=memory.get_profile()["profile"]))
        # Memory can change when Ollama runs. Recheck before voice generation.
        safely_memory_check()
        wav = safely(lambda: engine.synthesize(answer, data.language, data.mode))
        return wrap_audio(wav, transcript=data.text, reply=answer, language=data.language)
    return run_exclusive(work)


def safely_memory_check():
    try:
        resource_limits.require_memory(model_loaded=engine.status()["modelLoaded"])
    except resource_limits.VoiceMemoryLow as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


def handle_turn(data: VoiceTurnRequest):
    if not engine.status()["referenceReady"]:
        raise HTTPException(status_code=409, detail="Upload a voice reference clip first.")

    def work():
        audio = read_audio(data.audio_base64)
        transcript, detected = safely(lambda: engine.transcribe(audio))
        if not transcript:
            raise HTTPException(status_code=422, detail="Could not hear clear words. Try speaking again.")
        lang = "hi" if detected == "hi" else "en"
        answer = safely(lambda: engine.reply_to(transcript, mode=data.mode, language=lang,
                                                 profile=memory.get_profile()["profile"]))
        safely_memory_check()
        wav = safely(lambda: engine.synthesize(answer, lang, data.mode))
        return wrap_audio(wav, transcript=transcript, reply=answer, language=lang)
    return run_exclusive(work)


def save_profile(data: ProfileSaveRequest):
    return safely(lambda: memory.save_profile(data.profile, data.consent))


# Profile data is kept by explicit consent, and never includes audio/transcripts.
@app.get("/v1/profile", dependencies=[Depends(worker_auth)])
def protected_profile():
    return safely(memory.get_profile)


@app.post("/v1/profile", dependencies=[Depends(worker_auth)])
def protected_profile_save(data: ProfileSaveRequest):
    return save_profile(data)


@app.delete("/v1/profile", dependencies=[Depends(worker_auth)])
def protected_profile_delete():
    return safely(memory.delete_profile)


@app.get("/api/voice/profile", dependencies=[Depends(local_auth)])
def local_profile():
    return safely(memory.get_profile)


@app.post("/api/voice/profile", dependencies=[Depends(local_auth)])
def local_profile_save(data: ProfileSaveRequest):
    return save_profile(data)


@app.delete("/api/voice/profile", dependencies=[Depends(local_auth)])
def local_profile_delete():
    return safely(memory.delete_profile)


# Protected service-to-service routes. Never expose to anonymous public traffic.
@app.get("/v1/status", dependencies=[Depends(worker_auth)])
def protected_status():
    return get_status()


@app.post("/v1/reference", dependencies=[Depends(worker_auth)])
def protected_reference(data: AudioUpload):
    return receive_sample(data)


@app.delete("/v1/reference", dependencies=[Depends(worker_auth)])
def protected_delete(mode: str = "friend"):
    return remove_sample(mode)


@app.post("/v1/speak", dependencies=[Depends(worker_auth)])
def protected_speak(data: SpeechRequest):
    return handle_speak(data)


@app.post("/v1/chat", dependencies=[Depends(worker_auth)])
def protected_chat(data: ChatRequest):
    return handle_chat(data)


@app.post("/v1/turn", dependencies=[Depends(worker_auth)])
def protected_turn(data: VoiceTurnRequest):
    return handle_turn(data)


# Convenient one-process local prototype. Never bind this app to 0.0.0.0.
@app.get("/api/voice/status", dependencies=[Depends(local_auth)])
def preview_status():
    return {**get_status(), "authReady": False, "ownerSignedIn": False, "ttsReady": engine.status()["referenceReady"]}


@app.post("/api/voice/sample", dependencies=[Depends(local_auth)])
def preview_reference(data: AudioUpload):
    return receive_sample(data)


@app.delete("/api/voice/sample", dependencies=[Depends(local_auth)])
def preview_delete(mode: str = "friend"):
    return remove_sample(mode)


@app.post("/api/voice/speak", dependencies=[Depends(local_auth)])
def preview_speak(data: SpeechRequest):
    return handle_speak(data)


@app.post("/api/voice/chat", dependencies=[Depends(local_auth)])
def preview_chat(data: ChatRequest):
    return handle_chat(data)


@app.post("/api/voice/turn", dependencies=[Depends(local_auth)])
def preview_turn(data: VoiceTurnRequest):
    return handle_turn(data)


@app.get("/health")
def health():
    return {"service": "mini-private-local-voice", "status": "up"}


async def _run_realtime(websocket: WebSocket, *, allow_local_dev: bool, require_ticket: bool = False):
    from . import realtime
    session = realtime.MiniRealtimeSession(websocket, allow_local_dev_token=allow_local_dev,
                                           require_ticket=require_ticket)
    await session.handle_connection()


# Authentication happens BEFORE the WebSocket handshake is accepted, so a
# refused client never reaches model loading. Closing before accept() makes
# the server reject the upgrade (HTTP 403).
@app.websocket("/v1/realtime")
async def protected_realtime_ws(websocket: WebSocket):
    if (ws_auth.browser_origin_refused(websocket.url.path, websocket.headers.get("origin"))
            or not ws_auth.worker_token_ok(websocket.headers.get("x-mini-worker-token"))):
        await websocket.close(code=1008, reason="Worker authentication required")
        return
    await _run_realtime(websocket, allow_local_dev=False)


@app.websocket("/v1/realtime/browser")
async def browser_realtime_ws(websocket: WebSocket):
    # Only the Mini site may open this; session.start must then carry a valid
    # Vercel-issued ticket AND a Supabase session for the same user.
    if not ws_auth.realtime_origin_allowed(websocket.headers.get("origin")):
        await websocket.close(code=1008, reason="Origin not allowed")
        return
    await _run_realtime(websocket, allow_local_dev=False, require_ticket=True)


@app.websocket("/api/voice/realtime")
async def local_realtime_ws(websocket: WebSocket):
    if _local_error(websocket):
        await websocket.close(code=1008, reason="Localhost only")
        return
    await _run_realtime(websocket, allow_local_dev=True)


DIST = Path(__file__).resolve().parents[2] / "dist"
if DIST.is_dir():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="mini-ui")
