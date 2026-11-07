#!/usr/bin/env python3
"""Mini AI Phase 1B: CPU voice+brain benchmark for an 8-vCPU host.

The voice reference is kept on this machine. No ElevenLabs API is called.
Both Friend and Mentor voices are tested with the same warmed Chatterbox model.

From the repository root:
  MINI_CPU_THREADS=6 OMP_NUM_THREADS=6 MKL_NUM_THREADS=6 \
    .venv/bin/python -m services.voice_worker.benchmark_host --threads 6
Optional:
  .venv/bin/python -m services.voice_worker.benchmark_host --threads 6 --test-brain
"""
from __future__ import annotations

import argparse
import os
import resource
import sys
import time
import wave
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def available_memory_gib() -> float | None:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / (1024 * 1024)
    except (OSError, ValueError, IndexError):
        pass
    return None


def measure_tts(engine, mode: str, phrase: str, label: str) -> tuple[float, float]:
    start = time.perf_counter()
    wav = engine.synthesize(phrase, language="en", mode=mode)
    elapsed = time.perf_counter() - start
    engine.ensure_private_dir()
    output = engine.ROOT / f"benchmark_{mode}_{label}.wav"
    output.write_bytes(wav)
    output.chmod(0o600)
    with wave.open(str(output), "rb") as f:
        audio_seconds = f.getnframes() / f.getframerate()
    ratio = elapsed / audio_seconds if audio_seconds else float("inf")
    print(
        f"{mode.upper():6s} {label:4s}: {elapsed:.2f}s compute, "
        f"{audio_seconds:.2f}s audio, {ratio:.2f}x real-time factor",
        flush=True,
    )
    print(f"  Local output: {output}", flush=True)
    return elapsed, ratio


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threads", type=int, default=6, help="CPU threads for model inference, default 6")
    parser.add_argument("--test-brain", action="store_true", help="Also time an Ollama 1B response")
    args = parser.parse_args()
    if args.threads < 1 or args.threads > 32:
        parser.error("Provide between 1 and 32 CPU threads")
    if args.threads > (os.cpu_count() or args.threads):
        print("Warning: requested more threads than detected vCPUs", flush=True)

    # Must set these before importing PyTorch, Chatterbox or faster-whisper.
    for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "MINI_CPU_THREADS"):
        os.environ[key] = str(args.threads)
    os.environ.setdefault("MINI_OLLAMA_MODEL", "llama3.2:1b")
    os.environ.setdefault("MINI_WHISPER_MODEL", "tiny.en")
    print(f"Mini voice CPU benchmark | threads: {args.threads}", flush=True)
    print(f"CPU allocation: {os.cpu_count()} vCPUs | "
          f"available RAM: {available_memory_gib() or 0:.1f} GiB", flush=True)

    from services.voice_worker import engine
    for mode in ("friend", "mentor"):
        if engine.reference_for(mode) is None:
            print(f"ERROR: {mode} reference not installed on this server", flush=True)
            return 2

    import torch
    torch.set_num_threads(args.threads)
    try:
        torch.set_num_interop_threads(1)
    except RuntimeError:
        pass
    print(f"PyTorch {torch.__version__} | inference device: {engine._device()}", flush=True)
    if engine._device() != "cpu":
        print("Note: GPU detected; use this benchmark only for CPU-baseline comparison.")

    try:
        measure_tts(engine, "friend", "Hey! It's Mini. Let's figure this out together.", "cold")
        measure_tts(engine, "friend", "I'm here and I'm listening.", "warm")
        measure_tts(engine, "mentor", "What is one practical next step you can take today?", "warm")
    except Exception as exc:
        print(f"TTS FAILED: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1

    if args.test_brain:
        available = available_memory_gib()
        if available is not None and available < 2.0:
            print(
                f"SKIPPED Ollama: only {available:.2f} GiB available with Chatterbox loaded. "
                "Run the isolated brain benchmark after this process exits: "
                ".venv/bin/python -m services.voice_worker.benchmark_brain",
                flush=True,
            )
        else:
            print("Timing Ollama response (1B model, local host)...", flush=True)
            start = time.perf_counter()
            try:
                reply = engine.reply_to(
                    "I want to make progress on my project. What's my first step?",
                    mode="mentor",
                )
                print(f"Ollama response time: {time.perf_counter() - start:.2f}s | "
                      f"reply: {reply[:160]}", flush=True)
            except Exception as exc:
                print(f"OLLAMA FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
                return 1

    print(f"Peak process memory: {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024:.0f} MiB")
    print(f"Remaining available RAM: {available_memory_gib() or 0:.1f} GiB")
    print("These are sequential generation timings, NOT proof of streaming voice or concurrency.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
