#!/usr/bin/env bash
# Ubuntu 24.04, CPU-only Mini AI Phase 1B installer.
# Run from the cloned repository on your PRIVATE Linux server.
# Installs dependencies; never uploads audio or starts a public listener.
set -euo pipefail
cd "$(dirname "$0")/../.."

echo "== MINI CPU-ONLY INSTALL (Ubuntu 24.04) =="
echo "Installation downloads several gigabytes of model dependencies."
if [[ ! -r /etc/os-release ]]; then
  echo "OS metadata missing" >&2; exit 1
fi
. /etc/os-release
if [[ "$ID" != "ubuntu" ]]; then
  echo "Designed for Ubuntu." >&2; exit 1
fi
if [[ "$EUID" -ne 0 ]]; then
  echo "Run as root or via sudo. The resulting Python environment remains in this project." >&2; exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ffmpeg git build-essential pkg-config python3-venv python3-pip pipx ca-certificates

# Avoid changing Ubuntu's system Python 3.12; Chatterbox was tested on 3.11.
export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  pipx install uv
fi
uv python install 3.11
if [[ ! -x .venv/bin/python ]]; then
  uv venv --python 3.11 .venv
else
  .venv/bin/python -c 'import sys; assert sys.version_info[:2] == (3,11), "Existing .venv must use Python 3.11"'
  echo "Reusing existing Python 3.11 environment."
fi

# Keep EVERY dependency-resolution step on CPU PyTorch: Chatterbox's source
# dependency resolver may otherwise download massive CUDA wheels.
export UV_TORCH_BACKEND=cpu
uv pip install --python .venv/bin/python --index-url https://download.pytorch.org/whl/cpu \
  "torch==2.6.0" "torchaudio==2.6.0"

# Chatterbox Nano's published GitHub source is newer than the March PyPI wheel.
uv pip install --python .venv/bin/python \
  "git+https://github.com/resemble-ai/chatterbox.git@ab55923c27757c90cfcc407baa57dc25a7d25217"

uv pip install --python .venv/bin/python \
  "fastapi>=0.115,<1" "uvicorn>=0.30,<1" "httpx>=0.27,<1" \
  "faster-whisper>=1.1,<2" "soundfile>=0.12,<1"

.venv/bin/python - <<'PY'
import torch
from chatterbox.tts_turbo import ChatterboxTurboTTS
from faster_whisper import WhisperModel
print("PyTorch:", torch.__version__, "CUDA:", torch.cuda.is_available())
print("Chatterbox Nano API ready:", hasattr(ChatterboxTurboTTS, "from_pretrained"))
print("Worker dependencies: OK")
PY

echo "Dependency installation complete; first model inference downloads model weights."
echo "Next: ollama pull llama3.2:1b"
echo "Keep the private worker bound only to 127.0.0.1."
