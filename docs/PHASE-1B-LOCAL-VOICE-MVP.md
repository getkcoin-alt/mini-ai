# Phase 1B — First real Mini AI speech-to-speech browser test

Date: 2026-11-07. This playbook uses **the existing 8-vCPU Ubuntu 22.04 host**, the two private reference WAV files, Ollama llama3.2:1b, faster-whisper tiny.en and Chatterbox Nano. ElevenLabs is not called.

## Measured before integration

Two resident benchmark runs, each with two Friend turns:

| Run | Resident voice startup | Turn | LLM | Warm TTS | Text-to-voice total | Audio |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| 1 | 11.21 s | 1 | 4.86 s | 8.49 s | 13.35 s | 6.00 s |
| 1 | — | 2 | 3.21 s | 8.61 s | 11.82 s | 6.32 s |
| 2 | 12.16 s | 1 | 5.48 s | 16.40 s | 21.89 s | 13.36 s |
| 2 | — | 2 | 3.24 s | 7.94 s | 11.18 s | 5.72 s |

Peak resident Python RSS: **4290 MiB**; available RAM between stages and turns was generally **5.44–7.54 GiB**. These tests did not include Whisper or browser transport. The TTS runtime increases with speech duration. There is no substantiated real-time or concurrent-user performance claim yet.

## New runtime protections

- **Single heavy turn per process:** second simultaneous request gets HTTP 429 instead of launching another heavyweight model; localhost status and health remain responsive.
- **Memory gate:** default minimum 7.0 GiB available before first TTS model load and 2.5 GiB for an already-resident model. A check repeats between Ollama and TTS. This is a heuristic and cannot prevent all OOM incidents.
- **Optional prewarm:** `MINI_PRELOAD_TTS=1` loads Chatterbox once at process startup when there is adequate RAM, rather than making the user wait at the first utterance. Do not enable until sufficient RAM has been verified.
- **Short conversational answers:** Mini is prompted to give one specific, grounded spoken sentence, and the backend caps the voice response to a default of 160 characters. These are early CPU-MVP controls, not a replacement for actual conversational memory.
- **Single Python worker:** never run multiple Uvicorn workers or multiple copies of the same Chatterbox model on this shared machine.

## A. On Ubuntu: update and build the **private** browser demo

Do this only when no other Mini voice benchmark/worker is running. Do **not** stop unrelated Next.js, Java or Uvicorn services on this shared VPS.

```bash
cd /root/mini-ai
git pull --ff-only origin main
free -h

# Must have Node/npm installed; run in the existing repo.
node -v
npm -v
npm install
npm test
npm run build

# Confirm both recordings are present on the PRIVATE server.
ls -l /root/.mini-ai/voice/reference_friend.wav /root/.mini-ai/voice/reference_mentor.wav
```

## B. On Ubuntu: start the private voice worker

Run it in the foreground, with the terminal open:

```bash
cd /root/mini-ai
MINI_PRELOAD_TTS=1 MINI_CPU_THREADS=6 OMP_NUM_THREADS=6 MKL_NUM_THREADS=6 \
  bash services/voice_worker/start-local.sh
```

It binds to **127.0.0.1:8765 only**. The prewarm is optional and takes roughly 11–12 seconds based on prior separate benchmarks; its real runtime may differ. It does not start a public service.

In a **second Ubuntu SSH terminal**:

```bash
curl -fsS http://127.0.0.1:8765/health
curl -fsS http://127.0.0.1:8765/api/voice/status
```

Expected status fields when references are installed: `workerReady:true`, `referenceReady:true`, `voiceReady:true`, and, if prewarm succeeded, `modelLoaded:true`. The `inferenceBusy` flag can be true only while a heavy turn is executing.

## C. From MacBook: connect without publishing the server

Open **Mac Terminal**, separate from the Ubuntu terminal and replace the placeholder with the server's actual SSH hostname/IP:

```bash
ssh -N -L 8765:127.0.0.1:8765 root@YOUR_SERVER_IP
```

Leave the SSH tunnel running. On **the MacBook itself**, open:

**http://127.0.0.1:8765**

This is the **private localhost preview**, not the Vercel site. Your browser considers 127.0.0.1 a secure context for microphone permission, even though the local URL uses HTTP, because traffic is forwarded inside SSH. Do not bind Uvicorn to 0.0.0.0 or open port 8765 in the firewall.

In Mini AI, continue in demo mode, finish or skip onboarding, choose Friend or Mentor, and open the voice controls. If the browser displays the real local provider status, tap the microphone, record a short sentence, then tap again. The browser sends its recording to Whisper → Ollama → Chatterbox and plays the generated answer. This is **push-to-talk**, not full-duplex real-time speech.

## D. How to report the result

Capture: (1) the worker's status JSON, (2) the voice-turn outcome or first error, (3) current `free -h`, and (4) the spoken answer's approximate end-to-end delay measured from microphone stop until first playback. Do not share voice recordings, private IPs, SSH keys, tokens or users' personal conversations in logs.

## Do not activate public access yet

The Vercel deployment is intentionally not wired to this private worker because Google OAuth owner credentials, HTTPS gateway and per-user isolation are not yet configured. Do not point a public reverse proxy directly at the localhost-only FastAPI app; its `/api/voice/*` preview routes are not public-authenticated.

Once the microphone test passes, next phase is a minimal queue, server-side short-lived context (opt-in memory), a proper HTTPS service gateway exposing only authenticated `/v1/*`, and latency improvements (streaming Whisper/LLM/TTS when hardware allows).
