# Mini AI — First CPU Streaming Voice Experiment on NFC

**Purpose:** Compare Kyutai Pocket TTS with our proven Chatterbox Nano voice for Friend and Mentor. Do NOT replace production Mini AI inference while testing. This is an experiment, not a deploy command.

The owner reported two authorized reference clips already installed under /var/lib/mini-ai/voice/ on the private guest; never export or commit them. Pocket's voice-cloning weights may require accepting model access terms on Hugging Face through the operator's legitimate account. Do not put tokens into source files or command history.

## Preconditions

On the mini-ai-inference GUEST, not the nfc libvirt host:

- Confirm the current Mini service is healthy and check free RAM. Avoid running CPU-heavy benchmarks while users are chatting.
- Verify no other experiment is using the same test output files.
- Only run this if the authorized voices and model usage terms permit the experiment.
- Keep the original Chatterbox service and fallback unchanged.

### Prepare a separate Python environment INSIDE the guest

~~~bash
cd /home/ubuntu/mini-ai
git pull --ff-only origin main

free -h
sudo systemctl is-active mini-voice-worker
sudo stat -c '%U %a %n' /var/lib/mini-ai/voice/reference_friend.wav /var/lib/mini-ai/voice/reference_mentor.wav
python3 -m venv "$HOME/.venv-pocket"
"$HOME/.venv-pocket/bin/python" -m pip install -U pip
# Install CPU PyTorch FIRST, so the experiment doesn't pull CUDA packages:
"$HOME/.venv-pocket/bin/python" -m pip install --index-url https://download.pytorch.org/whl/cpu 'torch==2.6.0'
"$HOME/.venv-pocket/bin/python" -m pip install pocket-tts
~~~

If python3-venv is unavailable, install the appropriate Ubuntu guest package with apt and retry, **never on the nfc hypervisor**. This separate environment will not modify /opt/mini-ai/.venv used by the production worker.

Since the references are private and owned by mini-worker, run the benchmark as mini-worker. The experiment venv and script must be readable by that user. Verify directory traversal permissions first; do not loosen permissions on the private voice samples.

### Run the same phrase against two voice models

Run on the guest, only when its 16GiB memory budget has sufficient headroom and Mini is idle:

~~~bash
sudo -u mini-worker env \
  HOME=/var/lib/mini-ai HF_HOME=/var/lib/mini-ai/.cache/huggingface \
  OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 \
  /home/ubuntu/.venv-pocket/bin/python \
  /home/ubuntu/mini-ai/scripts/benchmark_pocket_tts.py \
  --mode friend --threads 4 --language english_18m_2026-10 \
  --reference-dir /var/lib/mini-ai/voice --confirm-rights

sudo -u mini-worker env \
  HOME=/var/lib/mini-ai HF_HOME=/var/lib/mini-ai/.cache/huggingface \
  OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 \
  /home/ubuntu/.venv-pocket/bin/python \
  /home/ubuntu/mini-ai/scripts/benchmark_pocket_tts.py \
  --mode mentor --threads 4 --language english_18m_2026-10 \
  --reference-dir /var/lib/mini-ai/voice --confirm-rights
~~~

Next, compare the default model by changing --language to english. Run experiments SEQUENTIALLY, not simultaneously. Run 4 and 6 thread tests only if service performance stays healthy. The script measures time-to-first-audio AFTER ready text, not end-of-user-speech. It writes to /var/lib/mini-ai/voice/comparisons/ (private 0700, output WAVs 0600).

If the gated model download fails, review and accept the official access conditions if eligible, authenticate the **mini-worker** Hugging Face cache safely, and retry. Never paste tokens or full audio into chat or issue comments.

### What should the connected AI agent report?

| Field | Required |
| --- | --- |
| Model and its version | Explicit tag (default english vs 18m October 2026) |
| Friend / Mentor reference resemblance | Blind qualitative rating against Chatterbox |
| Model load | seconds |
| Voice state preparation | seconds |
| First audio chunk after text known | milliseconds |
| Audio length and total generation | seconds |
| RTF (compute seconds / audio seconds) | numeric |
| CPU / RSS / host pressure | observed |
| Saved audio | private path only |
| Model license and gated-access confirmation | yes/no |

**Decision:** Adopt Pocket only when voice likeness remains good AND measured first-chunk/RTF beats Chatterbox. Keep the current workers, memory and auth untouched until then.

Sources: https://github.com/kyutai-labs/pocket-tts and https://kyutai-labs.github.io/pocket-tts/API%20Reference/python-api/
