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
python3 -m uvicorn services.voice_worker.app:app --host 127.0.0.1 --port 8765
