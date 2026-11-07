"""Private Mini Reflex WebSocket: recorded user turn -> incremental LLM + cloned WAV phrases.

EXPERIMENTAL / OPT-IN. Only a direct localhost browser over an SSH tunnel
can connect; never expose it via public Vercel rewrites or a reverse proxy.
The currently deployed /api/voice/turn HTTP route is preserved as fallback.

Recorded microphone audio is buffered up to 3 MB. STT is performed at the end
of the utterance (not incremental). Ollama tokens/clauses stream. Chatterbox
generates each approved-voice phrase as a WAV: this is *phrase-streaming*, not
native per-sample streaming TTS and it does not guarantee sub-second speech.

Barge-in stops browser playback immediately; server cancellation is cooperative
and may finish the currently running Chatterbox phrase before releasing the lock.
"""
from __future__ import annotations

import asyncio
import base64
import os
import threading
from urllib.parse import urlsplit

MAX_AUDIO_BYTES = 3_000_000
MAX_PHRASES = 5
MAX_TURN_SECONDS = 180


def local_websocket_allowed(ws) -> bool:
    """Direct localhost + matching browser origin; reject reverse-proxy tricks."""
    peer = getattr(getattr(ws, "client", None), "host", "")
    host = (ws.url.hostname or "").lower()
    if peer not in ("127.0.0.1", "::1") or host not in ("127.0.0.1", "localhost", "::1"):
        return False
    origin = ws.headers.get("origin")
    if not origin:
        return False
    try:
        ref = urlsplit(origin)
        target_port = ws.url.port or (443 if ws.url.scheme == "wss" else 80)
        port = ref.port or (443 if ref.scheme == "https" else 80)
        return (ref.scheme in ("http", "https") and
                ref.hostname == host and port == target_port and
                ref.username is None and ref.password is None and
                not ref.path.strip("/") and not ref.query and not ref.fragment)
    except ValueError:
        return False


async def run_live_turn(ws):
    """One connection is one utterance. Not an anonymous remotely usable API."""
    if os.environ.get("MINI_ENABLE_LIVE_WS", "0") != "1" or not local_websocket_allowed(ws):
        await ws.close(code=1008, reason="Private Mini streaming preview only")
        return

    from . import engine, memory, resource_limits
    from .streaming_lab import stream_reply

    await ws.accept()
    cancel = threading.Event()
    queue: asyncio.Queue = asyncio.Queue(maxsize=72)
    loop = asyncio.get_running_loop()
    mode = "friend"
    mime = "audio/webm"
    audio = bytearray()
    try:
        first = await asyncio.wait_for(ws.receive_json(), timeout=15)
        if not isinstance(first, dict) or first.get("type") != "start":
            await ws.close(code=1008, reason="Start event required")
            return
        mode = first.get("mode", "friend")
        mime = first.get("mime", "")
        if mode not in ("friend", "mentor") or mime not in (
            "audio/webm", "audio/webm;codecs=opus", "audio/mp4",
            "audio/ogg;codecs=opus", "audio/wav"
        ):
            await ws.close(code=1008, reason="Unsupported voice mode or recording format")
            return
        if not engine.reference_for(mode):
            await ws.send_json({"type": "error", "status": 409,
                                "message": "Approved Mini voice reference unavailable"})
            await ws.close(code=1000)
            return
        await ws.send_json({"type": "ready", "message": "Mini is listening"})
        while True:
            frame = await asyncio.wait_for(ws.receive(), timeout=50)
            if frame.get("type") == "websocket.disconnect":
                cancel.set()
                return
            if frame.get("bytes") is not None:
                chunk = frame["bytes"]
                if len(audio) + len(chunk) > MAX_AUDIO_BYTES:
                    await ws.send_json({"type": "error", "status": 413,
                                        "message": "Recording too large. Try a shorter question."})
                    await ws.close(code=1009)
                    return
                audio.extend(chunk)
                continue
            message = frame.get("text", "")
            if not message:
                continue
            import json
            try:
                request = json.loads(message)
            except (TypeError, ValueError):
                await ws.close(code=1008, reason="Invalid event")
                return
            if request.get("type") == "cancel":
                cancel.set()
                await ws.send_json({"type": "cancelled"})
                await ws.close(code=1000)
                return
            if request.get("type") == "end":
                break
            await ws.close(code=1008, reason="Unexpected event")
            return

        if len(audio) < 1000:
            await ws.send_json({"type": "error", "status": 422, "message": "No detectable speech."})
            await ws.close(code=1000)
            return

        def push(payload: dict):
            # Backpressure: avoid a producer blocking indefinitely on a disconnected client.
            if cancel.is_set():
                return
            def try_push():
                if queue.full():
                    cancel.set()
                else:
                    queue.put_nowait(payload)
            loop.call_soon_threadsafe(try_push)

        def produce():
            phrase_count = 0
            try:
                with resource_limits.reserve_inference(model_loaded=engine.status()["modelLoaded"]):
                    push({"type": "stage", "name": "transcribing"})
                    transcript, detected = engine.transcribe(bytes(audio))
                    if not transcript or not transcript.strip():
                        push({"type": "error", "status": 422, "message": "No clear speech detected."})
                        return
                    if cancel.is_set():
                        return
                    push({"type": "transcript", "text": transcript})
                    lang = "hi" if detected == "hi" else "en"
                    owner_profile = memory.get_profile()["profile"]
                    push({"type": "stage", "name": "thinking"})
                    for event in stream_reply(transcript, mode=mode, cancel=cancel, profile=owner_profile):
                        if cancel.is_set():
                            return
                        if event["type"] == "token":
                            # Caption tokens are informative, not proof of audio playback.
                            push({"type": "token", "text": event["text"]})
                        elif event["type"] == "clause":
                            if phrase_count >= MAX_PHRASES:
                                break
                            sentence = event["text"].strip()
                            if not sentence:
                                continue
                            push({"type": "stage", "name": "speaking"})
                            # Chatterbox can only cancel at a phrase boundary.
                            wav = engine.synthesize(sentence, lang, mode)
                            if cancel.is_set():
                                return
                            phrase_count += 1
                            push({"type": "audio", "mime": "audio/wav",
                                  "audio_base64": base64.b64encode(wav).decode("ascii"),
                                  "text": sentence, "part": phrase_count,
                                  "provider": "chatterbox-local"})
                    push({"type": "done", "phrases": phrase_count,
                          "note": "Incremental phrases; Chatterbox still generates each WAV in a batch."})
            except resource_limits.VoiceBusy:
                push({"type": "error", "status": 429, "message": "Mini is finishing another conversation."})
            except resource_limits.VoiceMemoryLow:
                push({"type": "error", "status": 503, "message": "Mini is protecting server memory."})
            except Exception:
                push({"type": "error", "status": 502, "message": "Private Mini streaming turn failed."})
            finally:
                # Even if a burst of token callbacks filled the bounded queue,
                # sender must ALWAYS receive a final marker and release the socket.
                def send_end_marker():
                    if queue.full():
                        cancel.set()
                        try:
                            queue.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                    queue.put_nowait({"type": "_closed"})
                loop.call_soon_threadsafe(send_end_marker)

        worker = asyncio.create_task(asyncio.to_thread(produce))

        async def read_cancel():
            try:
                while not cancel.is_set():
                    frame = await ws.receive()
                    if frame.get("type") == "websocket.disconnect":
                        cancel.set()
                        break
                    if frame.get("text"):
                        import json
                        try:
                            data = json.loads(frame["text"])
                        except ValueError:
                            cancel.set()
                            break
                        if data.get("type") == "cancel":
                            cancel.set()
                            break
            except Exception:
                cancel.set()

        listener = asyncio.create_task(read_cancel())
        try:
            while True:
                item = await asyncio.wait_for(queue.get(), timeout=MAX_TURN_SECONDS)
                if item["type"] == "_closed":
                    break
                if cancel.is_set() and item["type"] == "audio":
                    continue
                await ws.send_json(item)
        finally:
            listener.cancel()
            try:
                await asyncio.wait_for(worker, timeout=30)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                # Inference thread cannot be forcibly interrupted inside Chatterbox.
                # It retains the single inference lock until its current operation exits.
                cancel.set()
        try:
            if cancel.is_set():
                await ws.send_json({"type": "cancelled"})
            await ws.close(code=1000)
        except Exception:
            pass
    except (asyncio.TimeoutError, Exception):
        cancel.set()
        try:
            await ws.close(code=1011, reason="Mini streaming session ended")
        except Exception:
            pass
