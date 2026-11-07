#!/usr/bin/env python3
"""Measure Ollama separately from Chatterbox to avoid overlapping RAM peaks.

Run after the TTS benchmark exits:
    .venv/bin/python -m services.voice_worker.benchmark_brain

The benchmark makes one local Ollama request and reports time and memory.
It does not load Chatterbox, Whisper, or upload any data.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path


def available_gib() -> float | None:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 1048576
    except (OSError, IndexError, ValueError):
        return None
    return None


def main() -> int:
    model = os.environ.get("MINI_OLLAMA_MODEL", "llama3.2:1b")
    threads = int(os.environ.get("MINI_CPU_THREADS", "4"))
    # Safety: no configurable remote URL; never send test text outside localhost.
    endpoint = "http://127.0.0.1:11434/api/chat"
    before = available_gib()
    print(f"Mini AI — isolated Ollama benchmark | model={model} | threads={threads}", flush=True)
    print(f"Available RAM before: {before:.2f} GiB" if before is not None else "RAM unavailable", flush=True)
    if before is not None and before < 2.0:
        print("SAFETY STOP: under 2 GiB available. Check other processes before loading another model.", flush=True)
        return 2

    payload = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": "You are Mini, a practical and friendly AI. Answer in one short natural sentence."},
            {"role": "user", "content": "What should I do first if I want to build a useful daily AI companion?"}
        ],
        "options": {"num_thread": threads, "num_ctx": 1024, "num_predict": 60, "temperature": 0.4},
        # Unload when finished so this standalone diagnostic does not pin scarce RAM.
        "keep_alive": 0
    }
    request = urllib.request.Request(endpoint, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=110) as response:
            result = json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"Ollama request failed: {type(exc).__name__}: {exc}", flush=True)
        print("Check that Ollama is running and llama3.2:1b is installed.", flush=True)
        return 1
    elapsed = time.perf_counter() - start
    answer = str(result.get("message", {}).get("content", "")).strip()
    if not answer:
        print("Ollama returned an empty reply.", flush=True)
        return 1
    after = available_gib()
    print(f"Elapsed wall-clock: {elapsed:.2f}s", flush=True)
    print(f"Model load: {result.get('load_duration', 0) / 1e9:.2f}s" if isinstance(result.get("load_duration"), (int, float)) else "Model load: unavailable", flush=True)
    print(f"LLM evaluation: {result.get('eval_duration', 0) / 1e9:.2f}s" if isinstance(result.get("eval_duration"), (int, float)) else "LLM evaluation: unavailable", flush=True)
    print("Sample reply:", answer[:240], flush=True)
    print(f"Available RAM after: {after:.2f} GiB" if after is not None else "RAM unavailable", flush=True)
    print("This measures the LLM alone, NOT full speech-to-speech latency.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
