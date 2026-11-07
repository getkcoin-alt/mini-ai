#!/usr/bin/env python3
"""Run one genuine Mini AI speech turn against the private local worker.

Default (text input):
    python3 scripts/smoke_local_voice.py --mode friend
Optional microphone recording:
    python3 scripts/smoke_local_voice.py --mode mentor --audio ~/my_question.wav

Only connects to http://127.0.0.1:8765. Never prints bearer keys or raw audio.
"""
from __future__ import annotations
import argparse
import base64
import io
import json
from pathlib import Path
import time
import urllib.error
import urllib.request
import wave

URL = "http://127.0.0.1:8765"


def request(endpoint, data=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(
        URL + endpoint, data=body,
        headers={"Content-Type": "application/json"} if body else {},
        method="POST" if body else "GET",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.load(resp)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=("friend", "mentor"), default="friend")
    p.add_argument("--text", default="Hey Mini, I'm excited to build something useful. What's our next step?")
    p.add_argument("--audio", type=Path, help="Optional recorded speech under 3 MB; skips --text")
    args = p.parse_args()
    try:
        status = request("/api/voice/status")
        if not (status.get("workerReady") and status.get("referenceReady")):
            print("Voice worker or speaker reference not ready:", json.dumps({
                "workerReady": status.get("workerReady"),
                "referenceReady": status.get("referenceReady") }))
            return 2
        if args.audio:
            clip = args.audio.expanduser()
            if not clip.is_file() or not 1000 <= clip.stat().st_size <= 3000000:
                p.error("--audio must be a real voice recording of 1 KB–3 MB.")
            data = {"audio_base64": base64.b64encode(clip.read_bytes()).decode(),
                    "mime": "audio/wav", "mode": args.mode}
            endpoint = "/api/voice/turn"
        else:
            data = {"text": args.text[:160], "mode": args.mode, "language": "en"}
            endpoint = "/api/voice/chat"
        start = time.perf_counter()
        result = request(endpoint, data)
        elapsed = time.perf_counter() - start
        audio = base64.b64decode(result.get("audio_base64", ""), validate=True)
        with wave.open(io.BytesIO(audio), "rb") as wav:
            seconds = wav.getnframes() / wav.getframerate()
        output = Path.home() / ("mini_" + args.mode + "_smoke.wav")
        output.write_bytes(audio)
        output.chmod(0o600)
        print("Model:", status.get("brain"), "| Voice:", args.mode)
        print("You:", result.get("transcript") or args.text[:160])
        print("Mini:", result.get("reply"))
        print(f"End-to-end worker HTTP: {elapsed:.2f}s | Audio duration: {seconds:.2f}s")
        print("Private WAV:", output)
        print("This is a recorded-turn benchmark, not continuous duplex audio.")
        return 0
    except (urllib.error.URLError, ValueError, OSError, json.JSONDecodeError, wave.Error) as exc:
        print("Mini smoke test failed:", str(exc)[:250])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
