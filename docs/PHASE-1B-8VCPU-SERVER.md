# Mini AI Phase 1B — 8-vCPU Linux inference host

Updated 2026-11-07. New host specification supplied by owner: Ubuntu 22.04.5, 8 allocated x86_64 vCPUs on AMD EPYC 9J14, 15.6 GiB RAM (~5.1 GiB available when checked), 391 GB free NVMe. GPU was not specified.

## Decision

Use this server to benchmark and, if fast enough, host the private Mini AI voice inference worker. Keep Vercel for the frontend. The original 2-vCPU VPS can continue handling lightweight API/auth/storage if needed. **Do not assume a 96-core CPU allocation**: the VPS is assigned only 8 vCPUs. Do not assume a GPU exists without checking.

The uploaded benchmark_mini_nano.wav is a successful 24-kHz mono, 3.36-second output from the previous machine; it proves generation, not the new host's speed or exact timbre fidelity.

## 1 — Clone on the new server

~~~bash
git clone https://github.com/getkcoin-alt/mini-ai.git /root/mini-ai
cd /root/mini-ai
nproc
free -h
df -h .
command -v nvidia-smi && nvidia-smi || echo "No NVIDIA GPU detected"
~~~

If already cloned: cd /root/mini-ai && git pull --ff-only origin main

Available RAM was only about 5.1 GiB despite the 16 GB installed. Check free -h again before model load; existing workloads might cause OOM. Do not indiscriminately stop other applications.

## 2 — Install dependencies

~~~bash
cd /root/mini-ai
bash services/voice_worker/setup_cpu_ubuntu.sh
ollama pull llama3.2:1b
ollama list
~~~

Installer downloads packages, installs FFmpeg and isolated Python 3.11, and uses CPU PyTorch without overwriting system Python. Ubuntu 22.04 support is proposed but has not yet been verified on this particular host. Do not use --break-system-packages.

## 3 — Transfer the two authorized voices

Option A, from the **Mac Terminal** (using the ZIP already in Downloads):

~~~bash
scp -P 22 "$HOME/Downloads/MiniAI_Friend_Mentor_Voice_Pack.zip" root@NEW_SERVER_IP:/root/mini-ai/
~~~

Replace NEW_SERVER_IP and the port if needed. Then, on the **new Ubuntu server**:

~~~bash
cd /root/mini-ai
python3 services/voice_worker/install_reference_pack.py /root/mini-ai/MiniAI_Friend_Mentor_Voice_Pack.zip --confirm-rights
chmod 600 /root/mini-ai/MiniAI_Friend_Mentor_Voice_Pack.zip
~~~

Option B, copy the already installed references from the original VPS. On the **new server**, assuming SSH trust is already configured:

~~~bash
install -d -m 700 /root/.mini-ai/voice
scp root@OLD_SERVER_IP:/root/.mini-ai/voice/reference_friend.wav /root/.mini-ai/voice/
scp root@OLD_SERVER_IP:/root/.mini-ai/voice/reference_mentor.wav /root/.mini-ai/voice/
chmod 600 /root/.mini-ai/voice/reference_*.wav
~~~

Audio stays on private server disk, outside Git. Never send SSH keys or passwords in chat.

## 4 — Benchmark Friend and Mentor on 8 vCPUs

~~~bash
cd /root/mini-ai

MINI_CPU_THREADS=6 OMP_NUM_THREADS=6 MKL_NUM_THREADS=6 \
  .venv/bin/python -m services.voice_worker.benchmark_host --threads 6 --test-brain
~~~

Start with six threads to reserve some CPU for OS tasks. If memory is comfortable, compare four or eight threads in separate runs:

~~~bash
.venv/bin/python -m services.voice_worker.benchmark_host --threads 4
.venv/bin/python -m services.voice_worker.benchmark_host --threads 8
~~~

The benchmark measures cold and warm Friend/Mentor voice generation, generated audio durations, real-time factor and peak process memory. With --test-brain, it also times one Ollama 1B reply. Recorded test WAVs are in the private voice directory.

The new 8-vCPU server is promising, but GPU-free real-time speech is not guaranteed. Even with eight logical processors, performance will depend on shared host capacity and existing server workload.

## 5 — Start only the private worker (after successful benchmark)

~~~bash
cd /root/mini-ai
MINI_CPU_THREADS=6 bash services/voice_worker/start-local.sh
~~~

The worker allows API-only operation with no Node frontend build. It binds exclusively to 127.0.0.1:8765. Check from another SSH shell:

~~~bash
curl -sS http://127.0.0.1:8765/health
curl -sS http://127.0.0.1:8765/api/voice/status
~~~

Do not publicly open this port. For private browser access from your Mac use:

~~~bash
ssh -L 8765:127.0.0.1:8765 root@NEW_SERVER_IP
~~~

To connect the Vercel web UI later, build a separate authenticated HTTPS gateway that exposes only the protected /v1 routes, not unprotected localhost preview endpoints.

## 6 — MVP decision gate

- Listen to both styles across several sentences; sample-based cloning may not replicate the original emotional expression.
- Measure warm speech synthesis time, full recorded-turn latency, memory pressure and restart behavior.
- Keep the new server for inference if interaction is reasonably responsive, otherwise move only Chatterbox to a short-lived GPU function. Avoid running a GPU 24/7 until usage warrants it.
- Keep reference audio private and allow the voice owner to replace/delete it.

References: https://github.com/resemble-ai/chatterbox and the scripts under services/voice_worker in this repository.
