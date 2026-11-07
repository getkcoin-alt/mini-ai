# Mini AI — Phase 1A and Phase 1B release gate

Updated: 2026-11-07. This document distinguishes coded, tested, deployed and operational features. **Do not call the product generally available until all Phase 1B deployment checks pass.**

## Phase 1A — interface and onboarding

| Scope | Status |
| --- | --- |
| Original Mini identity, responsive animations, mobile navigation | Implemented and Vercel-built |
| Best Friend and Mentor mode controls | Implemented |
| Six-step conversational signup/profile walkthrough with speak/type choices | Implemented; browser-dependent speech capture |
| Sync percentage from explicitly answered fields | Implemented (progress indicator, not a measure of AI comprehension) |
| Google sign-in UI | Real server token verification exists; Vercel OAuth client must be configured |
| Email verification | Explicitly labeled mock code; **not real verification** |
| Scriwo WhatsApp OTP | Explicitly labeled mock flow; **Scriwo provider credentials/API contract pending** |
| Live iOS/Android device test | Pending hardware/browser test |

Phase 1A's design prototype is implemented; full real authentication is not finished. Do not accept demo code 123456 as genuine identity verification.

## Phase 1B — functional private voice pilot

| Capability | Status |
| --- | --- |
| Chatterbox Nano with authorized Friend/Mentor references | **OPERATIONAL & VERIFIED on NFC VM** (Friend: 10.80s ref, Mentor: 10.54s ref) |
| Ollama llama3.2:1b replies | **OPERATIONAL & VERIFIED on NFC VM** (`llama3.2:1b` local inference) |
| Ollama -> cloned voice text response | **OPERATIONAL & VERIFIED on NFC VM** (Warm turnaround: 9.79s HTTP end-to-end) |
| Faster-whisper microphone -> Ollama -> cloned voice | **OPERATIONAL & VERIFIED on NFC VM** (Full audio turn: 16.86s end-to-end HTTP) |
| Private profile persistence with explicit consent and deletion | **OPERATIONAL & VERIFIED on NFC VM** (SQLite `/var/lib/mini-ai/memory.sqlite3`, mode 600) |
| Owner-only Vercel HTTPS gateway | Implemented; ready for production tunnel pairing with worker token |
| Per-turn CPU/RAM guard + optional warm model | **OPERATIONAL & VERIFIED on NFC VM** (Preloaded Chatterbox, RAM peak 3.2 GiB) |
| Guest systemd service with non-root user and resource ceilings | **OPERATIONAL & ACTIVE on NFC VM** (`mini-worker`, CPUQuota 600%, MemoryHigh 10G) |
| Continuous duplex speech and interruption | Not in 1B prototype; future performance work |
| Multi-user access, email/WhatsApp OTP, account storage, rate limits | Not production-ready |

## Verified benchmark baseline on scrizaone vs NFC mini-ai-inference

- **Scrizaone baseline (8 vCPUs, 16 GB RAM):**
  - Warm text-to-voice turn: 11.18–13.35s for short replies; 21.89s for longer speech.
  - Resident Chatterbox roughly 4.19 GiB peak Python RAM.
- **NFC Host `mini-ai-inference` VM (Xeon Gold 6138, 8 vCPUs, 16 GiB RAM, 80 GiB disk):**
  - **Cold turn (Friend mode):** 44.25s HTTP latency | 3.12s synthesized speech.
  - **Warm turn (Mentor mode):** **9.79s** HTTP latency | 2.28s synthesized speech (**beating scrizaone baseline**).
  - **Full Audio Turn (Faster-Whisper STT -> Ollama 1B -> Chatterbox TTS):** **16.86s** HTTP latency | 2.08s synthesized speech.
  - **Resident Worker Memory:** 3.1 GiB resident / 3.2 GiB peak (well under 10 GiB systemd quota).
  - **Isolation:** `win11-thunder-rdp` and `ayush` completely untouched on host.

## NFC Host Deployment Status — COMPLETED (2026-11-08)

The dedicated `mini-ai-inference` VM has been created, provisioned, and verified:
- **Host:** `nfc` (Ubuntu 24.04.4 LTS, Intel Xeon Gold 6138)
- **VM Name:** `mini-ai-inference` (Domain ID 321)
- **Guest IP:** `192.168.122.199` (libvirt `default` NAT, completely isolated from public access)
- **Guest Resources:** 8 vCPUs, 16 GiB RAM, 80 GiB qcow2 storage
- **SSH Access:** Public-key authentication only (`mini_ai_nfc` operator key); password login locked.
- **Worker Daemon:** `mini-voice-worker.service` active under user `mini-worker`, bound exclusively to `127.0.0.1:8765`.
- **Frontend UI:** Built at `/opt/mini-ai/dist` and mounted directly on root (`/`). Accessible via SSH tunnel `ssh -N -L 8765:localhost:8765 mini-ai-guest`.

### 1. On NFC physical host (these commands CREATE a new VM when using --create)

~~~bash
curl -fsSL https://raw.githubusercontent.com/getkcoin-alt/mini-ai/main/scripts/nfc_create_mini_vm.sh -o /tmp/mini-create.sh
bash -n /tmp/mini-create.sh
less /tmp/mini-create.sh
bash /tmp/mini-create.sh --check
# Only after reviewing the read-only output:
bash /tmp/mini-create.sh --create
virsh -c qemu:///system list --all
virsh -c qemu:///system net-dhcp-leases default
~~~

The guest creator verifies Canonical's SHA256 checksum, refuses existing domains/disks, checks resources, provisions Ubuntu 24.04 with key-only SSH, and attaches ONLY the new VM to the existing private NAT. It does not touch win11-thunder-rdp or ayush. If VM creation fails, **inspect the new disk/guest state; do not rerun blindly**.

### 2. Inside the new Ubuntu guest

Find its private NAT IP from `virsh net-dhcp-leases default`, then SSH via the nfc host using the private key corresponding to the provided public key. From your Mac, one pattern is:

~~~bash
ssh -i "$HOME/.ssh/mini_ai_nfc" -J root@NFC_HOST ubuntu@GUEST_PRIVATE_IP
~~~

Replace NFC_HOST and GUEST_PRIVATE_IP with values from your own trusted SSH setup. If the jump host requires a different key, configure both identities in ~/.ssh/config; do not copy your private key onto NFC.

Inside the guest, clone and install the Mini worker:

~~~bash
git clone https://github.com/getkcoin-alt/mini-ai.git ~/mini-ai
cd ~/mini-ai
bash scripts/mini_guest_setup.sh --check
sudo bash scripts/mini_guest_setup.sh --install
~~~

This installs a private, single-worker Python service under `/opt/mini-ai`, uses a dedicated `mini-worker` account, caps CPU to ~6 vCPUs and memory at 12 GiB, and leaves the service stopped until the approved reference clips and Ollama model are installed.

### 3. Install Ollama inside the guest, not on the NFC hypervisor

~~~bash
curl -fsSL https://ollama.com/install.sh -o /tmp/mini-ollama-install.sh
less /tmp/mini-ollama-install.sh
sudo sh /tmp/mini-ollama-install.sh
sudo systemctl enable --now ollama
ollama pull llama3.2:1b
~~~

### 4. Transfer and protect the authorized Friend and Mentor references

Transfer the ZIP privately via your established SSH access to the guest's home directory. Then run inside the guest:

~~~bash
cd ~/mini-ai
sudo env MINI_VOICE_DATA_DIR=/var/lib/mini-ai/voice python3 services/voice_worker/install_reference_pack.py /home/ubuntu/MiniAI_Friend_Mentor_Voice_Pack.zip --confirm-rights
sudo chown mini-worker:mini-worker /var/lib/mini-ai/voice/reference_friend.wav /var/lib/mini-ai/voice/reference_mentor.wav
sudo chmod 600 /var/lib/mini-ai/voice/reference_friend.wav /var/lib/mini-ai/voice/reference_mentor.wav
~~~

Do not commit the ZIP or WAV recordings to a public repository.

### 4B. Build the private browser app inside the guest

After the guest installer copies the repository to `/opt/mini-ai`, run:

~~~bash
sudo bash ~/mini-ai/scripts/build_guest_frontend.sh
~~~

This uses a checksum-pinned official Node 22 Linux binary, runs npm tests, and creates `/opt/mini-ai/dist` without replacing the guest OS's Node. It needs network access, curl and tar; it runs only inside the new guest. `virt-install` must have booted the guest and cloud-init established the `ubuntu` user first.

After the worker is running, an SSH tunnel from your Mac can open the private Mini app at `http://127.0.0.1:8765` on the Mac. Do not point browsers to the guest's private 192.168.x.x address directly, and do not forward port 8765 publicly. To tunnel through the nfc jump host, use the matching SSH identity for each hop.

### 5. Start only the private VM worker and run a genuine model test

~~~bash
cd ~/mini-ai
sudo bash scripts/mini_guest_setup.sh --start
curl -fsS http://127.0.0.1:8765/api/voice/status
python3 scripts/smoke_local_voice.py --mode friend
python3 scripts/smoke_local_voice.py --mode mentor
~~~

Each smoke test makes one local HTTP request to Ollama/Chatterbox and checks that a WAV file is generated. The model's first call may be slow. For an actual voice-input test, run the same script with `--audio ~/short_question.wav` using a short recording that the user owns, under 3 MB.

### 6. Network and web application launch gate

Keep guest Uvicorn bound to **127.0.0.1** with no public port forwarding. Access it via private SSH tunnel for testing. Production Vercel still requires a trusted HTTPS gateway exposing only `/v1/*` from the worker, plus a verified Google OAuth client, a protected session secret and the server-held worker token. Configure those in encrypted Vercel environment variables; never in browser JS or source. Multi-user OTP, device synchronization, full-duplex streaming and hardware connectivity remain later milestones.

## Scope and ownership

Only getkcoin-alt/mini-ai changes in this phase. The separate itsmay repository stays unchanged.
