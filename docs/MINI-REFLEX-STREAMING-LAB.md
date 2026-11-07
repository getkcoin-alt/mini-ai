# Mini Reflex — Streaming Brain Lab (no production changes)

Date: 2026-11-08. **Experimental only.** The current NFC Mini voice worker still runs the verified Ollama 1B + Whisper + Chatterbox Nano implementation. The measured Pocket TTS **catalog** voice first chunks (152–255 ms) do not preserve the two authorized Mini voices.

## What this lab proves

`services/voice_worker/streaming_lab.py` streams from a local Ollama instance using `stream: true`, emits incremental tokens and stable clauses, supports a cooperative cancel flag, imposes output length bounds and validates localhost-only traffic. It stores no transcripts or memories.

`scripts/benchmark_streaming_brain.py` measures *first token* and *first completed spoken clause* separately from total text generation.

Neither file starts a server, adds a public endpoint, modifies `MINI_OLLAMA_KEEP_ALIVE`, swaps the TTS model, or implements streaming speech synthesis. This is a control experiment for our future WebSocket/LiveKit pipeline.

## Run on Mini guest, NOT NFC hypervisor

```bash
cd /home/ubuntu/mini-ai
git fetch origin experiment/mini-reflex-streaming
# To avoid changing the working deployment, clone/worktree into an isolated directory:
git worktree add /home/ubuntu/mini-reflex-experiment origin/experiment/mini-reflex-streaming
cd /home/ubuntu/mini-reflex-experiment
# Only while production Mini is idle; use its existing Python venv without modifying it.
MINI_STREAM_LAB_THREADS=4 /opt/mini-ai/.venv/bin/python -m scripts.benchmark_streaming_brain --mode friend --threads 4 --turns 3
MINI_STREAM_LAB_THREADS=4 /opt/mini-ai/.venv/bin/python -m scripts.benchmark_streaming_brain --mode mentor --threads 4 --turns 3
```

If `scripts` cannot be imported as a namespace package or path differs, use `PYTHONPATH=.` from the worktree. Do **not** run multiple model benchmarks while production speech is active. On shared CPU machines, benchmark impact matters as much as speed.

## Decisions / ordered next steps

1. **Keep Chatterbox default.** Pocket's streaming speed is promising, but existing catalog voices `alba` and `george` are NOT matches for Friend and Mentor.
2. **Custom-voice access gate:** accept official `kyutai/pocket-tts` Hugging Face terms using an authorized account; keep its token on the guest, never in GitHub. Re-run on both authorized Mini WAVs and compare blind voice likeness to Chatterbox.
3. Run the Ollama streaming brain lab above; collect median and p95 first token, first coherent clause, full text latency, memory and CPU load.
4. Run Moonshine streaming STT in an independent venv, compare accented/noisy English error rates and partial-word stability against Whisper.
5. If custom Pocket voice similarity passes, implement authenticated private audio transport with per-turn IDs, VAD, Ollama token streaming and Pocket streaming chunks. The public session must be verified through Supabase and an access-bound voice gateway.
6. Use real server cancellation for LLM/TTS, release resource locks only after inference exits; do not assume browser AbortController cancels a running model.
7. Preserve an HTTP `/turn` fallback and Chatterbox for failure recovery; test microphone-to-first-*meaningful*-audio median/p95 rather than vendor TTS-only first-chunk claims.

## Acceptance targets

- Actual Pocket custom Friend and Mentor voice similarity independently accepted by listening.
- First meaningful spoken answer p50 under 2.5s and p95 under 5s (aspirational).
- Barge-in stops user playback in 250 ms p95 and stops server work safely.
- Minimum 200 varied turns with quantified failures, 422 silence handling and bounded memory.
- No unsupported streaming speed claims before a real browser microphone turn passes.

Link: [Full real-time/auth/memory architecture](PHASE-1B-REALTIME-AUTH-LLM-MEMORY-RESEARCH.md).