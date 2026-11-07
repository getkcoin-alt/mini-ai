# Phase 1B — Ubuntu 24.04 CPU Host

**Owner's Linux report (2026-11-07):** Ubuntu 24.04.4, 2 logical CPU cores, 7.8 GiB RAM, 43 GB free disk, no NVIDIA GPU, Python 3.12, Node 20.20.2, Ollama installed, FFmpeg missing.

## CPU-first plan

- STT: faster-whisper tiny.en, INT8, two CPU threads
- LLM: Ollama llama3.2:1b
- English TTS: Chatterbox Nano (reference-conditioned) with Friend and Mentor clips
- Hindi: Defer heavy multilingual TTS until we have CPU measurements or a GPU
- Mode: push-to-talk; not real-time streaming

Nano's 3× real-time claim is measured on **eight cores**. Two cores may be much slower. Never promise realtime conversation without a benchmark.

## Step 1 — Update your existing clone

~~~bash
cd /root/mini-ai
git pull --ff-only origin main
bash services/voice_worker/linux_preflight.sh
~~~

## Step 2 — Install the CPU worker

~~~bash
cd /root/mini-ai
bash services/voice_worker/setup_cpu_ubuntu.sh
~~~

This installer uses apt for FFmpeg and build tools and pipx/uv for Python 3.11 without replacing the system Python 3.12. It installs CPU-only PyTorch 2.6, Chatterbox Nano from a reviewed GitHub commit, faster-whisper and FastAPI. It can download several gigabytes and does **not** start services or expose any ports. Review the script before running as root.

## Step 3 — Install lightweight Ollama brain

~~~bash
ollama list
ollama pull llama3.2:1b
curl --silent --show-error http://127.0.0.1:11434/api/tags | head -c 300
~~~

If Ollama is not running, inspect its installed service:

~~~bash
systemctl status ollama --no-pager
~~~

Do not start a second Ollama process when the system service already owns its port.

## Step 4 — Privately install the two authorized voice samples

The prepared ZIP is **only in this conversation**, never in public GitHub. Download it to your personal computer and transfer to Linux via SCP (substitute your server hostname; do not paste it here):

~~~bash
scp ~/Downloads/Mini_AI_Phase1B_Voice_References.zip root@YOUR_SERVER:/root/mini-ai/
~~~

Back in Linux:

~~~bash
cd /root/mini-ai
python3 services/voice_worker/install_reference_pack.py /root/mini-ai/Mini_AI_Phase1B_Voice_References.zip --confirm-rights
chmod 600 /root/mini-ai/Mini_AI_Phase1B_Voice_References.zip
~~~

The installer validates the WAV format and saves two private files under ~/.mini-ai/voice/reference_friend.wav and reference_mentor.wav. These files condition generation; this is **not training** a new model.

## Step 5 — Build local frontend

~~~bash
cd /root/mini-ai
npm install
npm test
npm run build
~~~

Node 20.20.2 meets the Vite Node 20.19+ requirement, though this repo targets Node 22 for cloud builds. npm may warn about engines. If your environment uses strict engine checks, use Node 22 for this step.

## Step 6 — Start the loopback-only server

~~~bash
cd /root/mini-ai
bash services/voice_worker/start-local.sh
~~~

From a second terminal:

~~~bash
curl http://127.0.0.1:8765/health
curl http://127.0.0.1:8765/api/voice/status
~~~

The app listens only on 127.0.0.1:8765, not the public internet. To see it on your personal computer, create a private SSH tunnel from that computer:

~~~bash
ssh -L 8765:127.0.0.1:8765 root@YOUR_SERVER
~~~

Open http://127.0.0.1:8765 locally. The production Vercel app will still show worker offline until a secured HTTPS worker gateway is configured.

## Step 7 — Benchmark before attempting realtime audio

~~~bash
cd /root/mini-ai
.venv/bin/python services/voice_worker/benchmark_cpu.py
~~~

The script generates a benchmark WAV in your private voice directory and prints cold/warm inference timing, output audio duration and peak memory. It does not upload voice audio. If the warm TTS latency is unacceptable, keep this VPS as the app/API server and run Chatterbox on a separate GPU system.

**Send back:** the first installation error if any, the Ollama model list, the safe worker status response, and benchmark times. Never share IP addresses, SSH keys, tokens, or the original voice samples in logs.

Source: https://github.com/resemble-ai/chatterbox and https://ollama.com/library/llama3.2.
