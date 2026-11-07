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

## 6 — First measured results on the 8-vCPU server (2026-11-07)

The owner ran the six-thread benchmark successfully, with both licensed references:

| Request | Generation wall-clock | Generated speech | Real-time factor |
| --- | ---: | ---: | ---: |
| Friend cold (including first-use model loading/download) | 105.74 s | 3.60 s | 29.37× |
| Friend warm | 3.33 s | 1.40 s | 2.38× |
| Mentor warm | 4.82 s | 3.08 s | 1.57× |

PyTorch 2.6.0+cpu. Peak Python process RSS: **3678 MiB**. Reported MemAvailable: **4.1 GiB before loading** and **0.7 GiB while the model remained loaded**. The shell returning after the benchmark does not imply that only 0.7 GiB remains now; recheck `free -h`. The Hugging Face first-use download was approximately 2.69 GB. Subsequent warm results do not include model download or startup.

**Decision:** custom voice synthesis works. It is still *slower than playback* (RTF > 1), and a full STT → LLM → TTS round-trip is not yet measured. The server is close to a memory limit with Chatterbox resident. Do **not** launch Ollama 1B + faster-whisper + Chatterbox simultaneously in production until memory under load is validated. Keep the original 2-vCPU VPS available for a small brain or gateway if splitting responsibilities proves necessary.

### Next safe diagnostics — no second Chatterbox load required

First, after the voice benchmark has exited:

~~~bash
cd /root/mini-ai
git pull --ff-only origin main
free -h
ps -eo pid,comm,rss --sort=-rss | head -12
ollama list
ollama ps
~~~

This reveals whether other services consume RAM and which Ollama models are resident. If the 1B model is not installed, `ollama pull llama3.2:1b` downloads it but does not force an inference session.

Then measure the LLM **in isolation**, with Chatterbox not running:

~~~bash
cd /root/mini-ai
MINI_CPU_THREADS=4 .venv/bin/python -m services.voice_worker.benchmark_brain
~~~

This script checks that at least 2 GiB of memory is available, times one local Ollama 1B reply, then requests the model unload to avoid pinning scarce RAM. The 2-GiB threshold is a conservative *preflight heuristic*, not a guarantee that all memory failures are prevented.

Do not run `benchmark_host --test-brain` while MemAvailable is low. The updated benchmark skips simultaneous Ollama if it sees <2 GiB available, but separate runs produce clearer measurements. If other important applications are hosted here, do not stop them to free memory without inspecting their role and confirming a maintenance plan.

## Troubleshooting — Ollama command not found (2026-11-07)

New server diagnostic: `ollama: command not found` and the isolated model benchmark receives `Connection refused` on localhost:11434. This is an **uninstalled Ollama service**, not a Chatterbox failure. The TTS benchmark succeeded independently.

Do **not** run `snap install ollama` just because Ubuntu suggests it; use the project's officially documented Linux installation to maintain a predictable systemd service. Review the downloaded script before execution:

~~~bash
cd /root/mini-ai
curl -fsSL https://ollama.com/install.sh -o /tmp/mini-ollama-install.sh
less /tmp/mini-ollama-install.sh
sh /tmp/mini-ollama-install.sh
command -v ollama
systemctl enable --now ollama
systemctl is-active ollama
curl -fsS http://127.0.0.1:11434/api/tags
~~~

If `systemctl` or `curl` fails, check `systemctl status ollama --no-pager` and `journalctl -u ollama -n 70 --no-pager`. Keep the Ollama API bound to **127.0.0.1**, not a public network interface. On a shared VPS, review existing resource usage and don't stop unrelated services to free RAM.

After the local Ollama API works:

~~~bash
ollama pull llama3.2:1b
ollama list
cd /root/mini-ai
MINI_CPU_THREADS=4 .venv/bin/python -m services.voice_worker.benchmark_brain
~~~

The isolated benchmark does **not** load Chatterbox and tells Ollama to unload the model after the test. It is not a full speech-to-speech benchmark. Report the time and RAM after the test, not any credentials.

Source: official upstream [Ollama Linux installation documentation](https://github.com/ollama/ollama/blob/main/docs/linux.mdx).

## 7 — MVP decision gate

- Listen to both styles across several sentences; sample-based cloning may not replicate the original emotional expression.
- Measure warm speech synthesis time, full recorded-turn latency, memory pressure and restart behavior.
- Keep the new server for inference if interaction is reasonably responsive, otherwise move only Chatterbox to a short-lived GPU function. Avoid running a GPU 24/7 until usage warrants it.
- Keep reference audio private and allow the voice owner to replace/delete it.

References: https://github.com/resemble-ai/chatterbox and the scripts under services/voice_worker in this repository.

## 8 — Ollama benchmark succeeded (2026-11-07)

The owner installed Ollama and independently benchmarked **llama3.2:1b** on the new server, with `MINI_CPU_THREADS=4`:

| Metric | Measured |
| --- | ---: |
| Available RAM before Ollama | 6.63 GiB |
| End-to-end model-call wall-clock | 4.20 s |
| Model loading | 3.07 s |
| Response token evaluation | 0.81 s |
| Available RAM immediately after | 5.32 GiB |

The LLM returned a coherent one-sentence answer. No simultaneous Chatterbox + Ollama inference was measured, and these figures must not be represented as a complete speech-to-speech turn.

### Next: memory-isolated text → brain → cloned voice test

**In a terminal on the new server:**

~~~bash
cd /root/mini-ai
git pull --ff-only origin main
free -h
ollama ps
.venv/bin/python -m services.voice_worker.benchmark_pipeline --mode friend
~~~

The new pipeline test uses **separate child processes** for reasoning and speech synthesis, so both heavy models do not remain loaded simultaneously. It checks that at least 4 GiB of memory is available before starting voice inference. The resulting file is:

`/root/.mini-ai/voice/mini_friend_pipeline_test.wav`

Once this works, test the Mentor style:

~~~bash
.venv/bin/python -m services.voice_worker.benchmark_pipeline --mode mentor
~~~

To additionally test Whisper, use `--audio /path/to/your_short_voice_input.wav` (a short, clear recording of the **user**, under 3 MB). Text-only tests intentionally skip speech recognition.

This validates a **staged prototype**. It is not evidence of warm continuous speech streaming or safe public multi-user hosting. The Ollama adapter now sets `keep_alive=0` by default to avoid retaining its memory alongside Chatterbox. For the live service, assess separating inference across the two existing servers or another GPU before allowing concurrent user requests.

