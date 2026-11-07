#!/usr/bin/env bash
# Run ONLY inside the newly created mini-ai-inference Ubuntu guest.
# Modes: --check (read only), --install (set up dedicated service), --start (require references + Ollama).
set -Eeuo pipefail
mode=--check
if (( $# > 0 )); then mode="$1"; fi
[[ "$mode" == --check || "$mode" == --install || "$mode" == --start ]] || {
  echo "Usage: sudo bash scripts/mini_guest_setup.sh [--check|--install|--start]" >&2; exit 2;
}
guest="$(hostname -s)"
[[ "$guest" == mini-ai-inference ]] || {
  echo "BLOCKED: run only inside the dedicated mini-ai-inference VM, not nfc or scrizaone." >&2; exit 2;
}
root="$(cd "$(dirname "$0")/.." && pwd)"
echo "Mini AI guest: $guest"
echo "Repo: $root"
echo "vCPUs: $(nproc)"
free -h
df -h /
if [[ "$mode" == --check ]]; then
  echo "READ-ONLY. No software or service changed."
  exit 0
fi
[[ "$EUID" == 0 ]] || { echo "Use sudo inside mini-ai-inference" >&2; exit 1; }
if [[ "$mode" == --install ]]; then
  [[ ! -e /opt/mini-ai || -d /opt/mini-ai ]] || {
    echo "BLOCKED: /opt/mini-ai exists but is not a directory"; exit 1;
  }
  # Copy reviewed Mini app source into an OS-owned path; protect the libvirt host.
  mkdir -p /opt/mini-ai
  cp -a "$root/." /opt/mini-ai/
  chown -R root:root /opt/mini-ai
  chmod 755 /opt/mini-ai
  cd /opt/mini-ai
  bash services/voice_worker/setup_cpu_ubuntu.sh
  id mini-worker >/dev/null 2>&1 || useradd --system --create-home --home-dir /var/lib/mini-ai --shell /usr/sbin/nologin mini-worker
  install -d -o mini-worker -g mini-worker -m 0700 /var/lib/mini-ai/voice
  install -d -o mini-worker -g mini-worker -m 0700 /var/lib/mini-ai/.cache
  install -d -o root -g root -m 0700 /etc/mini-ai
  if [[ ! -e /etc/mini-ai/worker.env ]]; then
    token="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
    umask 077
    cat > /etc/mini-ai/worker.env <<EOF
MINI_WORKER_TOKEN=$token
MINI_VOICE_DATA_DIR=/var/lib/mini-ai/voice
MINI_OLLAMA_URL=http://127.0.0.1:11434
MINI_OLLAMA_MODEL=llama3.2:1b
MINI_OLLAMA_KEEP_ALIVE=0
MINI_WHISPER_MODEL=tiny.en
MINI_CPU_THREADS=6
OMP_NUM_THREADS=6
MKL_NUM_THREADS=6
MINI_PRELOAD_TTS=1
MINI_MIN_COLD_GIB=7.0
MINI_MIN_WARM_GIB=2.5
MINI_MAX_REPLY_CHARS=160
EOF
    chmod 600 /etc/mini-ai/worker.env
  fi
  cat > /etc/systemd/system/mini-voice-worker.service <<EOF
[Unit]
Description=Mini AI private voice inference (single CPU worker)
After=network-online.target ollama.service
Wants=network-online.target
[Service]
Type=simple
User=mini-worker
Group=mini-worker
WorkingDirectory=/opt/mini-ai
Environment=HOME=/var/lib/mini-ai
Environment=HF_HOME=/var/lib/mini-ai/.cache/huggingface
EnvironmentFile=/etc/mini-ai/worker.env
ExecStart=/opt/mini-ai/.venv/bin/python -m uvicorn services.voice_worker.app:app --host 127.0.0.1 --port 8765 --workers 1
Restart=on-failure
RestartSec=6
UMask=0077
CPUQuota=600%
MemoryHigh=10G
MemoryMax=12G
TasksMax=512
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/mini-ai
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  echo "GUEST INSTALL COMPLETE. Service file installed, but NOT started."
  echo "Move owner-authorized voice WAVs privately to /var/lib/mini-ai/voice; owner mini-worker, mode 600."
  echo "Install Ollama inside the guest and pull llama3.2:1b before starting."
  exit 0
fi
# --start: fail closed unless required models and references are ready.
[[ -f /etc/systemd/system/mini-voice-worker.service ]] || {
  echo "Run --install first"; exit 1;
}
for style in friend mentor; do
  file="/var/lib/mini-ai/voice/reference_$style.wav"
  [[ -s "$file" ]] || { echo "Missing private $style reference: $file"; exit 1; }
  [[ "$(stat -c '%U' "$file")" == mini-worker ]] || {
    echo "Owner of $file must be mini-worker"; exit 1;
  }
done
command -v ollama >/dev/null || { echo "Install Ollama in this guest first"; exit 1; }
systemctl is-active --quiet ollama || { echo "Start Ollama service in this guest first"; exit 1; }
ollama list | grep -F 'llama3.2:1b' >/dev/null || {
  echo "Run: ollama pull llama3.2:1b"; exit 1;
}
systemctl enable --now mini-voice-worker.service
systemctl is-active --quiet mini-voice-worker.service || {
  journalctl -u mini-voice-worker -n 45 --no-pager; exit 1;
}
echo "PRIVATE WORKER ACTIVE (localhost only)."
curl --fail --silent http://127.0.0.1:8765/health || true
echo
