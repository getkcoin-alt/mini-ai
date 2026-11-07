#!/usr/bin/env bash
# Prints system capacity only; no tokens, keys, network identifiers or user paths.
set -u
echo "MINI AI - PHASE 1B LINUX CAPABILITY REPORT"
if [[ -r /etc/os-release ]]; then
  . /etc/os-release
  echo "OS: $PRETTY_NAME"
fi
echo "Kernel: $(uname -r)"
echo "CPU: $(nproc 2>/dev/null || echo unknown) logical processors"
if command -v free >/dev/null 2>&1; then
  echo "RAM: $(free -h | awk '/^Mem:/ {print $2}') total"
fi
if command -v df >/dev/null 2>&1; then
  echo "Available disk space: $(df -h . | awk 'NR==2 {print $4}')"
fi
if command -v nvidia-smi >/dev/null 2>&1; then
  echo "NVIDIA GPU:"
  nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader 2>&1 || echo "GPU driver is not working"
else
  echo "NVIDIA GPU: no nvidia-smi command (CPU fallback may be slower)"
fi
for cmd in python3 ffmpeg node npm ollama; do
  if command -v "$cmd" >/dev/null 2>&1; then
    if [[ "$cmd" == "ffmpeg" ]]; then
      echo "ffmpeg: available"
    elif [[ "$cmd" == "ollama" ]]; then
      echo "ollama: available"
    elif [[ "$cmd" == "node" ]]; then
      echo "node: $(node --version)"
    elif [[ "$cmd" == "python3" ]]; then
      echo "python3: $(python3 --version)"
    else
      echo "$cmd: available"
    fi
  else
    echo "$cmd: missing"
  fi
done
