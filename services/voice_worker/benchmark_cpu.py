#!/usr/bin/env python3
"""Benchmark real English reference-voice inference on CPU (nothing sent to external voice services)."""
import os
import resource
import sys
import time
import wave

os.environ.setdefault("MINI_OLLAMA_MODEL", "llama3.2:1b")
os.environ.setdefault("MINI_WHISPER_MODEL", "tiny.en")
os.environ.setdefault("MINI_CPU_THREADS", "2")
os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")
from services.voice_worker import engine

def main():
    print("Mini Phase 1B CPU-only voice benchmark", flush=True)
    if not engine.reference_for("friend"):
        print("Install a permitted voice reference before testing.")
        return 2
    start = time.perf_counter()
    print("Generating first voice output (this includes model weight loading)...", flush=True)
    sample = engine.synthesize("Hey, it's Mini. Your voice is ready to try!", mode="friend")
    cold = time.perf_counter() - start
    engine.ensure_private_dir()
    target = engine.ROOT / "benchmark_mini_nano.wav"
    target.write_bytes(sample)
    target.chmod(0o600)
    with wave.open(str(target), "rb") as wav:
        seconds = wav.getnframes() / wav.getframerate()
    print(f"First request: {cold:.2f}s; Audio: {seconds:.2f}s")
    if seconds:
        print(f"First-request real-time factor: {cold / seconds:.2f}x")
    print(f"Peak Python RSS: {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024:.0f} MiB")
    print(f"Saved private test audio at: {target}")
    start = time.perf_counter()
    engine.synthesize("I am happy to hear from you again!", mode="friend")
    warm = time.perf_counter() - start
    print(f"Warm inference: {warm:.2f}s")
    print("Decision:", "Use separate GPU for interactive speech." if warm > 10 else "Proceed to test end-to-end turns.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
