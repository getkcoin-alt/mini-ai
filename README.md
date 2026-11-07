# Mini AI ✦

**A little more human. A lot more you.**

Mobile-first Best Friend + Mentor companion. Phase 1A is a deployed interactive frontend; Phase 1B is a private, open-source voice prototype built from **faster-whisper → Ollama 1B → Chatterbox Nano** with two authorized reference styles. There is no ElevenLabs runtime dependency.

## Current operational truth

| Capability | Status |
| --- | --- |
| Responsive landing, companion orb, Friend/Mentor UI | Deployed to Vercel |
| Six-step speak/type onboarding and sync percentage | Implemented; browser voice support varies |
| Offline/browser scripted demo mode | Implemented, explicitly labelled |
| Google verified-ID-token login | Server code exists; OAuth config needed for hosted use |
| Email verification / Scriwo WhatsApp OTP | UI demonstrations only; provider integration pending |
| Custom Friend/Mentor generated speech | **Verified on scrizaone** (8-vCPU server) |
| Ollama text → Chatterbox voice | **Verified**; warm turns ~11–13s for short replies |
| Microphone → Whisper → Ollama → voice | Coded, needs live browser end-to-end test |
| Opt-in private profile memory and forgetting | Coded, single-owner; runtime test pending |
| New NFC dedicated VM | Provisioning tools ready; **not created from ChatGPT** |
| Public multi-user service, continuous full-duplex, hardware pairing | Not yet delivered |

A real Phase 1B pilot must be activated on a protected Linux machine and tested. **The public Vercel site remains a demonstration until the backend gateway, authentication and voice worker are connected.**

## Useful links

- [Live Mini frontend](https://mini-ai-gitkcoin.vercel.app)
- [Phase 1A + 1B release gate and exact commands](docs/PHASE-1A-1B-RELEASE-GATE.md)
- [Guarded NFC VM creator](scripts/nfc_create_mini_vm.sh) — read-only by default; explicit `--create`
- [Non-root Ubuntu guest installer](scripts/mini_guest_setup.sh)
- [Pinned Node 22 frontend build for private guest](scripts/build_guest_frontend.sh)
- [Local real voice HTTP smoke test](scripts/smoke_local_voice.py)
- [Voice model setup, permissions and benchmark](docs/VOICE-INTEGRATION.md)
- [Full feature roadmap](docs/MINI-AI-ROADMAP.md)

## Architecture

```text
Mini web app (Vercel OR private guest localhost)
  ├─ Six-step profile + Friend/Mentor mode
  ├─ Google owner sign-in (when configured)
  ├─ Explicit 'remember my profile' consent / forget control
  └─ Voice recorder + captions
        ↓ (localhost for development; authenticated HTTPS gateway for hosted access)
Private Python worker — 1 CPU-heavy inference turn at a time
  ├─ faster-whisper tiny.en: speech-to-text
  ├─ Ollama llama3.2:1b: relevant short answer
  ├─ Chatterbox Nano: reference-conditioned Friend/Mentor voice
  └─ opt-in SQLite profile facts only, no stored conversation audio
```

Existing voice references stay on private server disk; Git rejects common audio formats. Worker routes under `/v1/*` require a server-held token. The local preview routes are allowed only through a loopback-only listener and an SSH tunnel. Do not publicly expose them.

## Privacy and constraints

- The user must explicitly choose to save profile details; removing the profile deletes the private SQLite row.
- Current memory is **single-owner pilot** only, not isolated multi-account storage.
- No provider API calls to ElevenLabs. Source reference clips must be authorized.
- Microphone access requires consent and a secure context; the current voice UX is **push-to-talk**, not uninterrupted two-way streaming.
- Google OAuth, real email OTP and real Scriwo WhatsApp OTP need integration credentials and proper production abuse controls.
- Hardware pairing and full agentic actions are future work.

## Repository boundary

This project only changes `getkcoin-alt/mini-ai`. The broader `getkcoin-alt/itsmay` repo remains unchanged.
