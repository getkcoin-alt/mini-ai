# Mini AI — Phase 1 architecture & interaction contract

Updated: 2026-11-07  
Scope: **graphic-led frontend-first demo**, hosted as static web on Vercel. No changes to `itsmay` in this delivery.

## 0. What exists today

This repository started with a LICENSE only. The new UI is dependency-free static HTML/CSS/JavaScript so that a linked Vercel Git project can build and deploy without an API key or database. The orb is drawn with CSS, not a stock asset. The app is responsive and intentionally mobile-first at narrow widths.

### Screen map

```
Landing / living Mini graphic
  ├── Explore concept (guest-only voice UI)
  └── Start
       └── Choose identity entry
            ├── Google (UI preview only)
            ├── Email + six-digit demo OTP
            ├── WhatsApp + six-digit demo OTP (Scriwo later)
            └── Continue in demo mode
                 └── Mini asks 6 conversational questions
                      ├── Reply by typing
                      ├── Reply using browser speech recognition (if available)
                      ├── Hear the question using browser TTS (if available)
                      └── Skip any question and return later
                            └── My Space
                                 ├── Friend ↔ Mentor switch
                                 ├── Talk: browser STT → scripted response → browser TTS
                                 ├── Captions / optional text input
                                 ├── Our Dynamic (edit the profile)
                                 ├── Memories (planned)
                                 ├── Devices (planned)
                                 └── Preferences / clear local demo data
```

## 1. Design primitives

- Midnight background, lavender glow, pearl violet responsive face/orb, soft blue-green highlights.
- The playful face carries Mini's presence; minimal choreography to avoid feeling gimmicky.
- Voice CTA remains visually dominant. Transcripts are optional for accessibility.
- Mobile application shell with thumb-reachable bottom navigation; desktop dashboard with sidebar.
- `prefers-reduced-motion` disables animations.
- No "human AI" impersonation; copy says Mini is an AI.

## 2. Onboarding dialogue data model (mock local state)

```ts
type MiniProfile = {
  name: string;
  miniName: string;
  relationship: "friend" | "mentor" | "both";
  tone: "gentle" | "balanced" | "direct";
  focus: string;
  boundaries: string;
};
type ProfileDraft = {
  profile: MiniProfile;
  completed: Record<keyof MiniProfile, boolean>;
  hasTalked: boolean;
};
```

The prototype saves this object in `localStorage` at `mini-ai-design-preview-v1` only. It does not store spoken audio, transcripts, real OAuth tokens, phone verification, voiceprints or remote memories. Local storage is not appropriate for production sensitive data; replace with authenticated encrypted server storage and minimal local cache.

### "Profile sync" is a transparent UI indicator, not an AI confidence score

```
Name             15%
Mini nickname    10%
Friend/Mentor    20%
Tone             15%
Current focus    20%
Boundaries       10%
First trial talk 10%
TOTAL           100%
```

Completion marks the field as explicitly answered. Skipped fields do not earn points. The progress meter is **not** evidence of model comprehension, friendship or emotional intimacy. Real app capabilities must never be held hostage to artificially inflate this score.

## 3. Voice-first implementation today

```
Browser microphone (SpeechRecognition where supported)
  → transcript
  → local keyword-based, prewritten demo response
  → SpeechSynthesisUtterance where supported
  → browser speaker
```

- This is **not** a free local LLM or a production speech-to-speech system.
- Browser speech availability and network/privacy behavior varies by browser/OS. The UI provides keyboard fallback.
- The microphone is opened by user action; no background recording.
- Button presses can abort recognition or cancel speech playback. True barge-in, VAD and duplex streaming require real backend work.

## 4. Future Phase 1B service architecture

```
┌──────────── Mini web / native client ────────────────┐
│ Mic, VAD preview, local captions, permission UI      │
│ Profile confirmation + corrections + sync indicator │
└─────────────────────┬────────────────────────────────┘
                      │ HTTPS / WSS, short-lived session token
              ┌───────▼───────────────────────┐
              │ Auth + session gateway         │
              │ Google OIDC / email OTP        │
              │ Scriwo WhatsApp OTP adapter    │
              │ rate limit + tenant isolation  │
              └───────┬───────────────────────┘
                      │
              ┌───────▼───────────────────────┐
              │ Companion orchestrator         │
              │ Friend/Mentor persona          │
              │ context fetch, memory approval │
              │ tools require confirmation     │
              └───────┬───────────────────────┘
                      │
           ┌──────────▼─────────────────────────┐
           │ Ollama (e.g. llama3.2:3b)          │
           │ faster-whisper + VAD + Piper TTS  │
           │ existing itsmay concepts/adapters │
           └──────────┬─────────────────────────┘
                      │
                Isolated encrypted storage
                + audit + consent log
```

Itsmay already implements a **separate device-oriented local companion** under `core/companion/`; future integration requires checking its tenant model, auth and API constraints before exposing any service publicly. Do not expose its local APIs directly to anonymous browsers.

### Suggested API contract (proposal, not currently implemented)

| Action | Proposed endpoint | Required server behavior |
| --- | --- | --- |
| Start sign-in | `POST /v1/auth/start` | provider-specific flow, rate limiting |
| Verify email/phone | `POST /v1/auth/verify` | server validates code/token; no browser-supplied secret |
| Get/update profile | `GET/PATCH /v1/me/mini-profile` | authenticated user namespace and schema |
| Understand answer | `POST /v1/mini/onboarding/interpret` | LLM suggests structured draft; user confirms |
| Voice session | `WSS /v1/mini/voice` | auth token, audio chunks, interruption, end-of-turn, status |
| Memory consent | `POST /v1/mini/memories/confirm` | confirm, redact, store and audit |
| Memory control | `GET/DELETE /v1/mini/memories/:id` | inspect and erase within user namespace |
| Pairing start | `POST /v1/mini/devices/pair` | authenticated, challenge-bound device ownership |

No endpoint above is live. The browser **must not** hold Scriwo API secrets, Google client secrets, private keys, or model-provider credentials.

## 5. Scriwo OTP production flow (to be integrated later)

1. User enters their WhatsApp number and consents to receiving an authentication message.
2. Client calls our auth gateway (never Scriwo directly using a secret).
3. Gateway applies per-device, per-number and per-IP abuse limits, checks eligibility and calls the approved Scriwo OTP/template flow.
4. Gateway stores hashed challenge / expiry and never logs the OTP plaintext.
5. User enters the code; server validates attempt count, signature/code, expiration and one-time use before issuing short-lived sessions.
6. Account linking must prevent two providers from silently merging unrelated identities.

Actual Scriwo API documentation, template approval, delivery callbacks, pricing and policy must be confirmed before implementation; no provider endpoints are invented here.

## 6. Physical hardware migration principle

Start with a mobile app owning the session. Pair a BLE accessory for secure device control; audio routing goes through platform-supported Bluetooth audio/LE Audio or a validated protocol. Web Bluetooth is not universally available, notably on iOS browsers. Once hardware is selected, migrate the web UI into a native container/React Native as appropriate, and test background audio ownership, battery use, wake word and handoff. Never claim seamless cross-device continuity until it is measured on real devices.

## 7. Integration and release checklist

- [x] UI works without backend/secrets and is Vercel-compatible.
- [x] All authentication screens clearly state their demo-only status.
- [x] One question at a time, with typing, optional speech, corrections, skipping and persistence.
- [x] Profile and trial conversation progress is understandable.
- [x] Device and memory sections are explicitly future-facing.
- [ ] Validate mobile Safari and Android Chrome by hand.
- [ ] Production Google/email/Scriwo provider contracts.
- [ ] Server-side model orchestration with measured voice latency.
- [ ] Security/consent and accessibility testing before collecting real data.
- [ ] Native app/hardware proof-of-concept.

### Source references

- `itsmay/docs/mini.md`: existing fully-local engine direction.
- `itsmay/core/brain/prompts/system_mini.md`: warm friend personality.
- `itsmay/core/brain/prompts/system_mini_mentor.md`: candid mentor personality.
- `itsmay/core/companion/profiles.py`: device local per-person profile and memory namespace.
- `itsmay/docs/strategy.md`: narrow, measurable differentiation, memory and execution.

## 8. Local voice prototype evolution (2026-11-07)

The frontend-first Phase 1A demo now includes the code for a **private optional speech backend**. The previous browser SpeechRecognition / SpeechSynthesis preview remains the fallback, but real local-model speech paths are coded for voice-sample owners who run the worker. The actual GPU service is **not** running in the Vercel deployment.

```text
Mini mobile browser (record a 5–12-second utterance)
  → owner-only Vercel gateway (or localhost loopback demo)
  → private Python worker
  → faster-whisper (speech recognition)
  → Ollama llama3.2:3b (Friend or Mentor short reply)
  → Chatterbox Turbo/Nano/Multilingual V3 + authorized sample
  → waveform to browser speaker
```

Do not upload models, speaker audio or API secrets to GitHub. Only the private worker holds the reference recording. The signed Google user session is a **Mini AI security mechanism**, unrelated to ElevenLabs login. ElevenLabs accounts and API services are not needed by this stack. Details: [VOICE-INTEGRATION.md](VOICE-INTEGRATION.md).

**Status distinction:** the mobile UI and server routes compile and deploy; Python model loading, actual cloning fidelity, mobile capture, end-to-end latency and safe production ingress still need verification on real hardware.
