# Mini AI — Phase 1B NFC inference-server plan

Updated: 2026-11-07. This is a proposed migration plan; the NFC machine has NOT been accessed or benchmarked.

## Server comparison

| Server | Reported resources | Proposed role |
| --- | --- | --- |
| Original srv1628639 | 2 vCPU, 8 GB RAM, Ubuntu 24.04 | Lightweight gateway / other services |
| scrizaone | 8 vCPU, 16 GB RAM, Ubuntu 22.04 | Verified Chatterbox Nano + Ollama 1B; rollback |
| nfc | 20 physical cores/40 threads, 128 GB RAM (~60 GB available), 732 GB SSD free, Ubuntu 24.04.4 | Candidate private model host |

Intel's official Xeon Gold 6138 specification confirms 20 cores, 40 threads, Skylake architecture, 2 GHz base and AVX-512: https://www.intel.com/content/www/us/en/products/sku/120476/intel-xeon-gold-6138-processor-27-5m-cache-2-00-ghz/specifications.html

GPU capability was not provided. Do NOT assume GPU availability. NFC has been up 151 days; existing production workloads may need protection. Avoid automatic package installation or stopping services before inventory.

## Existing measured performance: scrizaone (8 vCPUs)

| Warm turn | Ollama 1B | Nano TTS | Total | Speech |
| --- | ---: | ---: | ---: | ---: |
| Friend run A, turn 1 | 4.86s | 8.49s | 13.35s | 6.00s |
| Friend run A, turn 2 | 3.21s | 8.61s | 11.82s | 6.32s |
| Friend run B, turn 1 | 5.48s | 16.40s | 21.89s | 13.36s |
| Friend run B, turn 2 | 3.24s | 7.94s | 11.18s | 5.72s |

Resident Chatterbox load: 11.21–12.16s on scrizaone; peak Python RSS ~4290 MiB. These are text-to-voice timings, not full microphone-to-speech results. More cores and RAM on NFC do not guarantee faster inference than a newer EPYC CPU.

## Phase A — read-only NFC inventory

On NFC, with existing SSH access, run:

~~~bash
hostname
nproc
lscpu | grep -E 'CPU\(s\)|Core\(s\) per socket|Socket\(s\)|Model name|NUMA node\(s\)'
free -h
df -h /
uptime
command -v nvidia-smi && nvidia-smi || echo "NVIDIA GPU not confirmed"
command -v lspci && lspci | grep -Ei 'NVIDIA|VGA|3D controller' || true
ps -eo pid,comm,rss --sort=-rss | head -12
command -v ffmpeg || true
command -v ollama || true
python3 --version
~~~

This does NOT install packages, start inference or change configuration. If nproc differs from 40, honor the actual CPU allocation/quotas rather than the hardware inventory.

## Phase B — prepare a standalone work directory

Only after reviewing the preflight and confirming package installation is safe for other workloads:

~~~bash
git clone https://github.com/getkcoin-alt/mini-ai.git /opt/mini-ai
cd /opt/mini-ai
sed -n '1,200p' services/voice_worker/setup_cpu_ubuntu.sh
# On explicit approval after review:
# sudo bash services/voice_worker/setup_cpu_ubuntu.sh
~~~

The script installs FFmpeg, Python 3.11 in a separate project .venv via uv, CPU-only PyTorch and the pinned Chatterbox source. It must not replace system Python. Model weights download at first use.

Move the two owner-authorized Friend and Mentor WAV files privately from scrizaone or from the Mac Downloads ZIP. Save them as reference_friend.wav and reference_mentor.wav under the chosen worker user's private ~/.mini-ai/voice directory with permissions 0600 and parent directory 0700. Never commit audio to public Git.

## Phase C — comparative CPU benchmarks

Start at **12 CPU threads**, not 40. Do not run multiple benchmarks concurrently or interfere with existing services.

~~~bash
cd /opt/mini-ai
MINI_CPU_THREADS=12 OMP_NUM_THREADS=12 MKL_NUM_THREADS=12 \
  .venv/bin/python -m services.voice_worker.benchmark_host --threads 12
~~~

If host load remains stable, separately compare **8 and 16** threads. The benchmark_host script fixes voice test phrases, giving a more comparable measurement than the LLM+TTS tests with variable reply lengths.

~~~bash
MINI_CPU_THREADS=8 OMP_NUM_THREADS=8 MKL_NUM_THREADS=8 \
  .venv/bin/python -m services.voice_worker.benchmark_host --threads 8
MINI_CPU_THREADS=16 OMP_NUM_THREADS=16 MKL_NUM_THREADS=16 \
  .venv/bin/python -m services.voice_worker.benchmark_host --threads 16
~~~

After choosing a thread setting and installing local Ollama 1B, run the resident brain+voice benchmark with the same prompt as the scrizaone baseline:

~~~bash
MINI_CPU_THREADS=12 OMP_NUM_THREADS=12 MKL_NUM_THREADS=12 \
  .venv/bin/python -m services.voice_worker.benchmark_resident --mode friend --threads 12
~~~

Collect cold load, warm TTS, audio duration, LLM timings, resident memory usage and any observed impact on other services. Do not call CPU inference real-time based on core count alone.

## Proposed architecture if NFC wins

~~~text
Vercel Mini voice-first UI
     ↓ verified user / HTTPS
Trusted API gateway and permissions
     ↓ private authenticated service-to-service connection
NFC worker: faster-whisper + local Ollama + resident Chatterbox
     ↓ generated user-approved voice
Browser / mobile app

scrizaone: fallback, rolling comparison / other services
Original VPS: light gateway / existing applications
~~~

Keep NFC's worker bound to 127.0.0.1 during tests. Do not directly expose FastAPI /api/voice/* localhost preview routes to the internet. A production web connection requires an authenticated TLS gateway exposing only protected /v1/* routes, server-side secrets, quotas and per-user separation.

## Decision rule

- If NFC is demonstrably faster and has spare CPU/RAM without affecting other services, make it primary inference.
- If NFC is slower under load, keep scrizaone and consider an on-demand GPU only when proven necessary.
- If NFC has a usable GPU, benchmark GPU-aware Chatterbox Turbo separately; no GPU has been confirmed.
- Regardless of hardware, test microphone -> Whisper -> Ollama -> custom voice end to end before public onboarding.

## Proof status

- Completed: original voices, Ollama 1B and resident Chatterbox Nano tested on scrizaone.
- Pending: NFC GPU inspection and service workload inventory.
- Pending: NFC benchmark at 8/12/16 threads and actual real-time factor.
- Pending: authenticated Mini mobile browser to private-worker connection.
- Pending: continuous duplex interruption support.

## Verified nfc preflight — 2026-11-07

The owner verified **40 logical CPUs / 20 physical cores, one NUMA node, 125 GiB RAM with 80 GiB available, 732 GB free SSD, no NVIDIA GPU detected**, and load averages of 0.86/3.62/4.71. Swap totals 17 GiB, with 1.8 GiB used; that is not by itself proof of current pressure.

**Critical finding:** nfc is currently running two substantial qemu-system-x86 processes, approximately **31.0 GiB and 7.4 GiB RSS**, plus gunicorn, Python and Tor processes. It is likely an active QEMU/KVM virtualization host, not a spare server dedicated to Mini. Do not change the existing virtual machines, hypervisor services, network or firewall. Avoid installing Mini AI dependencies directly on the host until its VM responsibilities are understood.

### Safe read-only virtualization inventory

~~~bash
command -v virsh && virsh list --all || true
systemd-detect-virt
stat -fc %T /sys/fs/cgroup
systemctl --version | head -1
lscpu | grep -E 'Model name|Flags|Hypervisor' | cut -c 1-220
ps -eo pid,comm,%cpu,%mem,rss --sort=-rss | head -12
~~~

virsh might be absent even when QEMU is in use; do not install it just for this check.

### Deployment recommendation

**Preferred:** a new private test VM managed through the existing virtualization environment, initially **6–8 vCPUs, 12–16 GiB memory and 60–100 GB private disk**, contingent on remaining host headroom. This is a proposed allocation, not a VM that has been created. Confirm available management tools and resource reservations before provisioning.

**Alternative:** isolate a nonprivileged worker in its own service cgroup/container with CPU and RAM limits, after verifying what tools are already installed. Ubuntu 24.04 systemd resource controls allow CPUQuota=600% (approximately the maximum CPU time of six logical CPUs), MemoryHigh=10G and MemoryMax=12G, though these limits cannot guarantee VM latency is unaffected. See https://manpages.ubuntu.com/manpages/noble/man5/systemd.resource-control.5.html .

Benchmark the isolated worker against scrizaone's **11–13-second short warm text-to-voice turns**. Test both Friend and Mentor, Ollama, Whisper, memory, VM latency and browser audio before changing production routing. No NVIDIA GPU was detected; 40 threads and 80 GiB available memory do not establish low-latency speech by themselves.

Keep scrizaone as the already-proven inference machine and retain the existing Vercel frontend unchanged until the private nfc environment has passed an authenticated end-to-end test.
