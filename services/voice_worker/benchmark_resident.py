#!/usr/bin/env python3
"""Benchmark warm (resident) Chatterbox + local Ollama on the 8-vCPU Mini host.

Unlike benchmark_pipeline.py (one Python process PER stage), this keeps
the TTS model alive between turns, just like the FastAPI worker already does.

Run only when >=7 GiB RAM is available, no other Mini worker runs on 8765,
and the host is not undergoing other memory-intensive work:
  MINI_CPU_THREADS=6 OMP_NUM_THREADS=6 MKL_NUM_THREADS=6 \
    .venv/bin/python -m services.voice_worker.benchmark_resident --mode friend

Results are measured, not projected. Audio remains private. No ElevenLabs.
"""
from __future__ import annotations

import argparse
import os
import resource
import sys
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path


def available_gib():
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 1048576
    except (OSError, IndexError, ValueError):
        return None
    return None


def require_memory(min_gib: float, stage: str):
    free = available_gib()
    if free is None:
        raise RuntimeError("Cannot determine available RAM; refusing to load heavyweight models.")
    print(f"Memory available before {stage}: {free:.2f} GiB", flush=True)
    if free < min_gib:
        raise RuntimeError(f"SAFETY STOP: need >= {min_gib:.1f} GiB available before {stage}. "
                           "Other server workloads must not be interrupted.")


def ensure_no_existing_voice_worker():
    try:
        with urllib.request.urlopen("http://127.0.0.1:8765/health", timeout=1) as response:
            if response.status == 200:
                raise RuntimeError("Mini API worker already runs at 127.0.0.1:8765. "
                                   "Avoid a second heavy model process on this shared server.")
    except urllib.error.URLError:
        return


def generated_seconds(data: bytes) -> float:
    from io import BytesIO
    with wave.open(BytesIO(data), "rb") as wav:
        return wav.getnframes() / wav.getframerate()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("friend", "mentor"), default="friend")
    parser.add_argument("--threads", type=int, default=6)
    parser.add_argument("--question", default="Mini, what's one useful step to make today productive?")
    args = parser.parse_args()
    if not 1 <= args.threads <= min(os.cpu_count() or 32, 32):
        parser.error("--threads must be between 1 and the machine's vCPU count.")
    if not args.question or len(args.question) > 250:
        parser.error("--question must have 1–250 characters.")

    ensure_no_existing_voice_worker()
    require_memory(7.0, "the resident TTS model")
    for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "MINI_CPU_THREADS"):
        os.environ[key] = str(args.threads)
    os.environ.setdefault("MINI_OLLAMA_KEEP_ALIVE", "0")
    os.environ.setdefault("MINI_OLLAMA_MODEL", "llama3.2:1b")
    os.environ.setdefault("MINI_WHISPER_MODEL", "tiny.en")

    from services.voice_worker import engine
    if engine.reference_for(args.mode) is None:
        raise RuntimeError(f"No {args.mode} reference installed on the private worker.")
    if engine._device() != "cpu":
        raise RuntimeError("CPU benchmark only; use the GPU benchmark for a CUDA machine.")
    import torch
    torch.set_num_threads(args.threads)
    try:
        torch.set_num_interop_threads(1)
    except RuntimeError:
        pass

    # Cached process-wide by engine._TTS_MODELS. This initial load happens
    # once per worker boot, not every conversation.
    print(f"Preloading Chatterbox Nano (threads={args.threads})...", flush=True)
    started = time.perf_counter()
    engine._get_tts("en")
    load = time.perf_counter() - started
    print(f"TTS model load: {load:.2f}s", flush=True)
    require_memory(2.5, "a local Ollama response")

    print("Running 2 short replies with the SAME TTS model resident...", flush=True)
    for index in (1, 2):
        require_memory(2.5, f"reply {index}")
        start = time.perf_counter()
        reply = engine.reply_to(args.question, mode=args.mode, language="en")
        think_s = time.perf_counter() - start
        require_memory(1.4, f"voice generation {index}")

        start = time.perf_counter()
        wav = engine.synthesize(reply, language="en", mode=args.mode)
        voice_s = time.perf_counter() - start
        duration = generated_seconds(wav)

        engine.ensure_private_dir()
        path = engine.ROOT / f"mini_{args.mode}_resident_turn{index}.wav"
        path.write_bytes(wav)
        path.chmod(0o600)
        print(f"Turn {index}: LLM {think_s:.2f}s + warm TTS {voice_s:.2f}s"
              f" = {think_s + voice_s:.2f}s, generated {duration:.2f}s audio", flush=True)
        print(f"Mini: {reply[:240]}", flush=True)
        print(f"Private output: {path}", flush=True)
        require_memory(1.0, f"turn {index} completion")

    mem_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    print(f"Peak Python resident memory: {mem_mb:.0f} MiB", flush=True)
    print("No speech recognition or browser/network latency included.", flush=True)
    print("No public endpoint was started and no persistent service was changed.", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"Benchmark stopped: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(2)
