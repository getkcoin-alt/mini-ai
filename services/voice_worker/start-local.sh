#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
if ! command -v ffmpeg >/dev/null; then
  echo "ffmpeg is required for voice file decoding." >&2
  exit 1
fi
if ! command -v ollama >/dev/null; then
  echo "Install Ollama and run: ollama pull llama3.2:3b" >&2
  exit 1
fi
if [ ! -d dist ]; then
  echo "Build the Mini AI frontend first: npm install && npm run build" >&2
  exit 1
fi
# Only loopback is permitted for the local no-auth preview.
export MINI_OLLAMA_MODEL="${MINI_OLLAMA_MODEL:-llama3.2:1b}"
export MINI_WHISPER_MODEL="${MINI_WHISPER_MODEL:-tiny.en}"
export MINI_CPU_THREADS="${MINI_CPU_THREADS:-2}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-2}"
export MKL_NUM_THREADS="${MKL_NUM_THREADS:-2}"
if [[ ! -x .venv/bin/python ]]; then
  echo "No Python virtual environment. Run bash services/voice_worker/setup_cpu_ubuntu.sh first." >&2
  exit 1
fi
exec .venv/bin/python -m uvicorn services.voice_worker.app:app --host 127.0.0.1 --port 8765 --workers 1
