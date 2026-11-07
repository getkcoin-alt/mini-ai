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
import hmac
import os
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import engine

app = FastAPI(title="Mini AI Private Voice Worker", docs_url=None, redoc_url=None, openapi_url=None)
MAX_BASE64_LENGTH = 4_100_000


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


class VoiceTurnRequest(BaseModel):
    audio_base64: str = Field(min_length=1, max_length=MAX_BASE64_LENGTH)
    mime: str = Field(default="audio/webm", max_length=70)
    mode: str = Field(default="friend", pattern="^(friend|mentor)$")


def worker_auth(x_mini_worker_token: str | None = Header(default=None)):
    expected = os.environ.get("MINI_WORKER_TOKEN", "")
    if len(expected) < 32 or not x_mini_worker_token or not hmac.compare_digest(expected, x_mini_worker_token):
        raise HTTPException(status_code=401, detail="Worker authentication required")


def local_auth(request: Request):
    # A reverse-proxy exposing this app publicly would be unsafe: intentionally
    # require direct localhost requests for uncredentialed local UI alias paths.
    host = request.client.host if request.client else ""
    requested_host = (request.url.hostname or "").lower()
    if host not in ("127.0.0.1", "::1") or requested_host not in ("127.0.0.1", "localhost", "::1"):
        raise HTTPException(status_code=403, detail="This preview endpoint is localhost-only.")
    origin = request.headers.get("origin")
    if origin:
        try:
            from urllib.parse import urlsplit
            parsed = urlsplit(origin)
            if parsed.scheme != "http" or parsed.hostname != requested_host or parsed.port != request.url.port:
                raise HTTPException(status_code=403, detail="Cross-origin access denied.")
        except ValueError:
            raise HTTPException(status_code=403, detail="Invalid request origin.")


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
    return {**engine.status(), "workerReady": True, "localStandalone": True}


def receive_sample(data: AudioUpload):
    if data.consent is not True:
        raise HTTPException(status_code=400, detail="Confirm that you own the voice or have permission to reproduce it.")
    audio = read_audio(data.audio_base64)
    duration = safely(lambda: engine.save_reference(audio, data.mode))
    return {"saved": True, "mode": data.mode, "durationSeconds": duration, "referenceReady": True, "location": "private-worker-disk"}


def remove_sample(mode: str = "friend"):
    if mode not in ("friend", "mentor"):
        raise HTTPException(status_code=400, detail="Invalid voice style")
    return {"removed": engine.delete_reference(mode), "mode": mode, "referenceReady": engine.status()["referenceReady"]}


def handle_speak(data: SpeechRequest):
    wave = safely(lambda: engine.synthesize(data.text, data.language, data.mode))
    return wrap_audio(wave, language=data.language)


def handle_chat(data: ChatRequest):
    if not engine.status()["referenceReady"]:
        raise HTTPException(status_code=409, detail="Upload a voice reference clip first.")
    answer = safely(lambda: engine.reply_to(data.text, mode=data.mode, language=data.language))
    wav = safely(lambda: engine.synthesize(answer, data.language, data.mode))
    return wrap_audio(wav, transcript=data.text, reply=answer, language=data.language)


def handle_turn(data: VoiceTurnRequest):
    if not engine.status()["referenceReady"]:
        raise HTTPException(status_code=409, detail="Upload a voice reference clip first.")
    audio = read_audio(data.audio_base64)
    transcript, detected = safely(lambda: engine.transcribe(audio))
    if not transcript:
        raise HTTPException(status_code=422, detail="Could not hear clear words. Try speaking again.")
    lang = "hi" if detected == "hi" else "en"
    reply = safely(lambda: engine.reply_to(transcript, mode=data.mode, language=lang))
    wav = safely(lambda: engine.synthesize(reply, lang, data.mode))
    return wrap_audio(wav, transcript=transcript, reply=reply, language=lang)


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


DIST = Path(__file__).resolve().parents[2] / "dist"
if DIST.is_dir():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="mini-ui")
