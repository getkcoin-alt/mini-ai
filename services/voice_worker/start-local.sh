#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
if ! command -v ffmpeg >/dev/null; then
  echo "ffmpeg is required for voice file decoding." >&2
  exit 1
fi
if ! command -v ollama >/dev/null; then
  echo "Install Ollama and run: ollama pull llama3.2:1b" >&2
  exit 1
fi
if [ ! -d dist ]; then
  echo "No built frontend found. Starting the private API worker only (Vercel still hosts the UI)."
fi
# Only loopback is permitted for the local no-auth preview.
export MINI_OLLAMA_MODEL="${MINI_OLLAMA_MODEL:-llama3.2:1b}"
export MINI_WHISPER_MODEL="${MINI_WHISPER_MODEL:-tiny.en}"
# Use up to 6 threads by default; leave some capacity for OS/Ollama on 8-vCPU hosts.
# Override with MINI_CPU_THREADS=4 or =8 when benchmarking.
vcpus="$(nproc)"
if (( vcpus > 6 )); then recommended_threads=6; else recommended_threads="$vcpus"; fi
export MINI_CPU_THREADS="${MINI_CPU_THREADS:-$recommended_threads}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-$MINI_CPU_THREADS}"
export MKL_NUM_THREADS="${MKL_NUM_THREADS:-$MINI_CPU_THREADS}"
if [[ ! -x .venv/bin/python ]]; then
  echo "No Python virtual environment. Run bash services/voice_worker/setup_cpu_ubuntu.sh first." >&2
  exit 1
fi
exec .venv/bin/python -m uvicorn services.voice_worker.app:app --host 127.0.0.1 --port 8765 --workers 1
