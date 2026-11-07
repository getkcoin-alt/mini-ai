#!/usr/bin/env python3
"""A/B benchmark Pocket TTS streaming voice cloning without touching Mini's worker.

Examples on a dedicated TEST venv (not the running mini-voice-worker venv):
  python scripts/benchmark_pocket_tts.py --mode friend --confirm-rights \
      --language english_18m_2026-10 --threads 4
  python scripts/benchmark_pocket_tts.py --mode mentor --confirm-rights \
      --language english --threads 4

Install pocket-tts in that separate virtual environment. The official cloning
weights can require accepting Hugging Face model terms; do not paste HF_TOKEN
into a command or logs. Runs locally once weights are cached. Never uploads the
reference recording to ElevenLabs or a hosted inference endpoint.

Reports MODEL LOAD, VOICE STATE creation, first audio chunk, generation elapsed,
audio duration, RTF, peak RSS. All voice/audio files stay in a private directory.
Model availability, CPU speed and voice similarity must be VERIFIED on NFC.
"""
from __future__ import annotations

import argparse
import os
import resource
import sys
import time
import wave
from pathlib import Path

TEST_PHRASE = (
    "Hey, I'm here with you. Tell me the one thing you're most excited to build today."
)


def available_gib():
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 1048576
    except (ValueError, OSError, IndexError):
        return None
    return None


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=("friend", "mentor"), required=True)
    p.add_argument("--reference-dir", type=Path, default=Path.home() / ".mini-ai" / "voice")
    p.add_argument("--output-dir", type=Path, default=Path.home() / ".mini-ai" / "voice" / "comparisons")
    p.add_argument("--language", choices=(
        "english", "english_18m_2026-10", "english_7m_2026-10",
        "english_2m_2026-10",
    ), default="english_18m_2026-10")
    p.add_argument("--threads", type=int, default=4)
    p.add_argument("--text", default=TEST_PHRASE)
    p.add_argument("--confirm-rights", action="store_true", help="Confirm authorization for this recording")
    args = p.parse_args()
    if not args.confirm_rights:
        p.error("Explicit --confirm-rights is required before conditioning on a voice.")
    if not 1 <= args.threads <= 32:
        p.error("--threads must be 1–32.")
    if not 1 <= len(args.text) <= 220:
        p.error("--text must be 1–220 characters; short phrases permit fair comparisons.")

    reference_dir = args.reference_dir.expanduser().resolve()
    ref = reference_dir / f"reference_{args.mode}.wav"
    if not ref.is_file():
        p.error(f"No private {args.mode} reference found in {reference_dir}")
    if not 10000 <= ref.stat().st_size <= 3_000_000:
        p.error("Voice recording must be 10 KB–3 MB.")
    free = available_gib()
    if free is not None and free < 4:
        p.error(f"Only {free:.2f} GiB RAM is currently available. Stop safely.")
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    output_dir.chmod(0o700)
    print("Mini CPU streaming TTS experiment (NOT the live Mini service)", flush=True)
    print(f"Model: {args.language}; threads: {args.threads}; mode: {args.mode}", flush=True)
    print(f"Available RAM: {free:.2f} GiB" if free is not None else "RAM unavailable", flush=True)

    try:
        import numpy as np
        import torch
        from pocket_tts import TTSModel
    except ImportError as exc:
        print(f"Install CPU Pocket TTS into a separate experiment venv: {exc}", file=sys.stderr)
        return 2

    torch.set_num_threads(args.threads)
    start = time.perf_counter()
    try:
        model = TTSModel.load_model(language=args.language)
    except Exception as exc:
        print(f"MODEL LOAD FAILED: {type(exc).__name__}: {str(exc)[:260]}", file=sys.stderr)
        print("The original cloning weights may require HF access acceptance.", file=sys.stderr)
        return 2
    load_sec = time.perf_counter() - start

    start = time.perf_counter()
    try:
        voice_state = model.get_state_for_audio_prompt(str(ref))
    except Exception as exc:
        print(f"VOICE STATE FAILED: {type(exc).__name__}: {str(exc)[:260]}", file=sys.stderr)
        return 2
    state_sec = time.perf_counter() - start
    output = output_dir / f"mini_{args.mode}_{args.language}_stream.wav"
    # Write only after voice state is ready; no reference bytes enter output logs.
    first_chunk_sec = None
    frames = 0
    stream_start = time.perf_counter()
    try:
        with wave.open(str(output), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(int(model.sample_rate))
            for chunk in model.generate_audio_stream(voice_state, args.text):
                samples = chunk.detach().float().cpu().numpy().reshape(-1)
                if samples.size == 0:
                    continue
                if first_chunk_sec is None:
                    first_chunk_sec = time.perf_counter() - stream_start
                pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
                wav.writeframes(pcm.tobytes())
                frames += samples.size
    except Exception as exc:
        print(f"STREAM FAILED: {type(exc).__name__}: {str(exc)[:260]}", file=sys.stderr)
        try: output.unlink(missing_ok=True)
        except OSError: pass
        return 1
    generation_sec = time.perf_counter() - stream_start
    output.chmod(0o600)
    if not frames or first_chunk_sec is None:
        print("No audio emitted; benchmark failed.", file=sys.stderr)
        output.unlink(missing_ok=True)
        return 1
    duration_sec = frames / float(model.sample_rate)
    print(f"Model load: {load_sec:.3f}s")
    print(f"Voice state preparation: {state_sec:.3f}s")
    print(f"FIRST AUDIO CHUNK: {first_chunk_sec:.3f}s after text was supplied")
    print(f"Total generation: {generation_sec:.3f}s, audio produced: {duration_sec:.3f}s")
    print(f"RTF: {generation_sec / duration_sec:.3f} (lower is better)")
    print(f"Peak Python RSS: {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024:.0f} MiB")
    print(f"Private WAV: {output}")
    print("IMPORTANT: This does NOT include STT, Ollama, browser/WebSocket or perceived voice similarity.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
