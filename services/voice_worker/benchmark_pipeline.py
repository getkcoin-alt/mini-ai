#!/usr/bin/env python3
"""Stage-isolated Mini AI pipeline test for memory-constrained CPU servers.

Examples:
 .venv/bin/python -m services.voice_worker.benchmark_pipeline
 .venv/bin/python -m services.voice_worker.benchmark_pipeline --mode mentor
 .venv/bin/python -m services.voice_worker.benchmark_pipeline --audio /path/to/short.wav

Each heavy stage runs in a separate process and exits before the next loads.
This benchmarks the three components, not full-duplex or simultaneous serving.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

ROOT = Path(os.environ.get("MINI_VOICE_DATA_DIR") or (Path.home() / ".mini-ai" / "voice")).expanduser()
PHASES = ("stt", "brain", "tts")


def available_gib():
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 1048576
    except (OSError, IndexError, ValueError):
        pass
    return None


def stage(name, payload, result_path):
    from services.voice_worker import engine
    if name == "stt":
        file = Path(payload["audio"]).expanduser()
        if not file.is_file() or file.stat().st_size > 3000000:
            raise ValueError("Voice input must be a real file under 3 MB.")
        transcript, detected = engine.transcribe(file.read_bytes())
        if not transcript:
            raise ValueError("Whisper did not detect speech.")
        outcome = {"transcript": transcript, "detected": detected}
    elif name == "brain":
        reply = engine.reply_to(payload["text"], mode=payload["mode"], language="en")
        outcome = {"reply": reply}
    elif name == "tts":
        output = ROOT / ("mini_" + payload["mode"] + "_pipeline_test.wav")
        generated = engine.synthesize(payload["reply"], mode=payload["mode"], language="en")
        output.write_bytes(generated)
        output.chmod(0o600)
        with wave.open(str(output), "rb") as wav:
            duration = wav.getnframes() / wav.getframerate()
        outcome = {"output": str(output), "audioSeconds": round(duration, 2)}
    else:
        raise ValueError("Unknown stage")
    result_path.write_text(json.dumps(outcome), encoding="utf8")
    result_path.chmod(0o600)


def run_child(name, payload, temp_path):
    input_file = temp_path / (name + "-in.json")
    result_file = temp_path / (name + "-out.json")
    input_file.write_text(json.dumps(payload), encoding="utf8")
    input_file.chmod(0o600)
    args = [sys.executable, "-m", "services.voice_worker.benchmark_pipeline",
            "--stage", name, "--input-json", str(input_file),
            "--result-json", str(result_file)]
    print("Starting", name.upper(), "stage...", flush=True)
    started = time.perf_counter()
    try:
        finished = subprocess.run(
            args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, timeout={"stt": 100, "brain": 110, "tts": 250}[name],
            check=False,
        )
    except subprocess.TimeoutExpired as err:
        raise RuntimeError(f"{name.upper()} timed out; its child process was stopped.") from err
    elapsed = time.perf_counter() - started
    if finished.returncode != 0 or not result_file.exists():
        last = "\n".join((finished.stdout or "").splitlines()[-12:])
        raise RuntimeError(f"{name.upper()} failed ({finished.returncode}):\n{last}")
    result = json.loads(result_file.read_text(encoding="utf8"))
    free = available_gib()
    print(f"{name.upper()}: {elapsed:.2f}s; RAM available: {free:.2f} GiB" if free is not None
          else f"{name.upper()}: {elapsed:.2f}s", flush=True)
    return result, elapsed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", default="Hi Mini, what is one practical step I can take today?")
    parser.add_argument("--audio", help="Optional user-supplied short speech clip, under 3 MB")
    parser.add_argument("--mode", choices=("friend", "mentor"), default="friend")
    parser.add_argument("--stage", choices=PHASES, help=argparse.SUPPRESS)
    parser.add_argument("--input-json", help=argparse.SUPPRESS)
    parser.add_argument("--result-json", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.stage:
        if not args.input_json or not args.result_json:
            parser.error("Internal stage requires input and result paths")
        payload = json.loads(Path(args.input_json).read_text(encoding="utf8"))
        stage(args.stage, payload, Path(args.result_json))
        return 0

    if len(args.text) > 250:
        parser.error("Test message must contain at most 250 characters.")
    import urllib.error
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:8765/health", timeout=1) as res:
            if res.status == 200:
                print("SAFETY STOP: voice worker already running on port 8765. Stop it before this benchmark.")
                return 2
    except urllib.error.URLError:
        pass

    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    ROOT.chmod(0o700)
    if not (ROOT / f"reference_{args.mode}.wav").is_file():
        print("No private reference found for:", args.mode)
        return 2
    memory = available_gib()
    print("Mini isolated speech pipeline:", args.mode, "| RAM available:", memory, "GiB")
    if memory is not None and memory < 4:
        print("SAFETY STOP: fewer than 4 GiB available. Do not load Chatterbox.")
        return 2
    # Avoid loading Whisper, LLM and Chatterbox into one process.
    times = {}
    with tempfile.TemporaryDirectory(prefix=".mini-test-", dir=ROOT) as directory:
        folder = Path(directory)
        try:
            if args.audio:
                result, times["stt"] = run_child("stt", {"audio": args.audio}, folder)
                message = result["transcript"]
                print("Whisper transcript:", message[:250])
            else:
                message = args.text
                print("STT skipped — use --audio for a complete speech-input test.")
            result, times["llm"] = run_child(
                "brain", {"text": message, "mode": args.mode}, folder
            )
            print("Mini reply:", result["reply"][:450])
            memory = available_gib()
            if memory is not None and memory < 4:
                print(f"SAFETY STOP: {memory:.2f} GiB available after Ollama. TTS not started.")
                return 2
            output, times["tts"] = run_child(
                "tts", {"reply": result["reply"], "mode": args.mode}, folder
            )
            print("Voice file:", output["output"])
            print("Audio duration:", output["audioSeconds"], "seconds")
            print("Stage times:", ", ".join(f"{k}={t:.2f}s" for k, t in times.items()))
            print(f"Total isolated model-process time: {sum(times.values()):.2f}s")
            print("NOT a live streaming or multi-user latency test.")
            return 0
        except (RuntimeError, OSError, ValueError, json.JSONDecodeError) as err:
            print("PIPELINE ERROR:", err, file=sys.stderr)
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
