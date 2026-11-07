# Mini AI — Modular Realtime Voice Architecture (Phase 1B → 1C)

Date: 2026-11-08. Scope: \`getkcoin-alt/mini-ai\` ONLY; do not touch \`itsmay\`. Status: **frontend implemented, gateway and NFC pipeline not deployed**. Audio frame formats and events below are a **project-specific contract** to implement; they are not asserted to be the native Kyutai Unmute protocol.

## Product decision

Reuse the existing Mini AI Friend/Mentor prompts and local LLM. No ElevenLabs, OpenRouter, hosted STT, hosted TTS, extra API provider, or proprietary speech service needed. The minimum deployment stack is:

- Browser/mobile web PWA frontend and optionally Vercel **same-origin authenticated WSS relay** (Vercel Functions support WebSocket connections as of 2026-10-20). Vercel serves **no** LLM/STT/TTS inference.
- Existing Supabase Auth/Postgres: Google/email real user identity and opt-in per-user memory, RLS. Scriwo WhatsApp OTP separate, currently OFF; do not require it for streaming MVP.
- Existing private NFC \`mini-ai-inference\` guest: Silero VAD + local streaming STT + local Ollama LLM + Kyutai Pocket TTS streaming conditioned on BOTH authorized private Friend/Mentor references. Retain Chatterbox fallback until Pocket's custom-voice model is legitimately available and voice likeness passes A/B.

Kyutai **Unmute** is an open-source reference architecture for a text LLM plus streaming STT+TTS; its high-quality server TTS (1.6B parameters) and STT can be GPU-oriented. On CPU-only NFC use Pocket TTS (100M/18M as measured) and a CPU streaming STT benchmark. Do NOT install Unmute's whole Docker stack and replace our running LLM or auth.

Official references:
- https://github.com/kyutai-labs/unmute
- https://github.com/kyutai-labs/unmute/blob/main/docs/browser_backend_communication.md
- https://kyutai.org/next/unmute/
- https://kyutai.org/tts/
- https://github.com/kyutai-labs/pocket-tts
- https://vercel.com/changelog/websocket-support-is-now-generally-available

## Measured reality vs aspirational target

Last owner-supplied NFC baseline: 22/23 requests HTTP 200 (1 intentional no-speech 422), average end-to-end ~13.5 seconds; Ollama complete response ~4.9s and Chatterbox ~7.8s. Pocket TTS with catalog \`alba\`/\`george\` gave first audio chunk 152–255ms and RTF 0.46–0.87. These catalog voices are **NOT** our authorized Mini voices. Pocket arbitrary voice cloning weights are gated at https://huggingface.co/kyutai/pocket-tts.

**500–800ms is a stretch target, NOT a currently achieved latency or engineering guarantee.** Measure \`end_of_speech → first *meaningful* played audio\`, not \`text arrived → first TTS chunk\` or pre-recorded acknowledgement. Report median/p95 over ≥200 utterances and show voice fidelity checks. If the CPU cannot achieve that range without GPU or quality sacrifices, report the actual distribution and recommend achievable optimization.

## Stream contract: \`mini.realtime.v1\`

The current frontend:
- \`mini-realtime-protocol.js\` defines a binary PCM protocol and same-origin WS path \`/api/voice/realtime\`.
- \`public/mini-capture.worklet.js\` emits mono signed PCM16 LE at 16kHz, **20ms/640-byte frames**, resampling from the browser device rate; it exports an RMS **meter only**, not simulated VAD.
- \`public/mini-playback.worklet.js\` accepts output PCM16 at 24kHz, smoothly resamples to browser output rate, and maintains a ≤5s bounded ring buffer with a ~60ms playback jitter start.
- \`mini-realtime-client.js\` requires a verified Supabase account, checks \`/api/voice/realtime-config\`, creates **same-origin** WSS (or ws://localhost only in local dev), sends Supabase JWT only inside the first WebSocket frame, then streams microphone frames. Never put JWT in WS query strings/URLs.
- \`mini-realtime-ui.js\` displays actual VAD/STT/LLM/TTS stage events, user transcript, streamed answer, barge-in, and time to first meaningful output. Audio never starts while the readiness gate is OFF.
- \`api/voice/realtime-config.js\` validates a real Supabase user token using the publishable project key. It advertises enabled only when BOTH \`MINI_REALTIME_ENABLED=true\` and \`MINI_REALTIME_GATEWAY_READY=true\`. Neither variable has been enabled.
- An authenticated WSS gateway at \`/api/voice/realtime\` must still be implemented by the NFC/backend agent; if using Vercel WebSocket Functions it must proxy only to an authenticated TLS-secured NFC ingress and never share worker master credentials with the browser.

### Control events (JSON text frames)

Browser → server:
\`\`\`json
{"type":"session.start","protocol":"mini.realtime.v1","access_token":"<SUPABASE_ACCESS_TOKEN>","mode":"friend","audio_input":{"format":"pcm16","channels":1,"sample_rate":16000,"frame_ms":20},"audio_output":{"format":"pcm16","channels":1,"sample_rate":24000},"playback_ack":true}
{"type":"playback.progress","response_id":"r1","heard_ms":700}
{"type":"response.cancel","response_id":"r1","heard_ms":700,"reason":"barge-in"}
{"type":"session.end"}
\`\`\`

Server → browser (send \`session.ready\` only AFTER verified JWT, explicit user authorization, concurrency gate, and no account mismatch):
\`\`\`json
{"type":"session.ready"}
{"type":"input.vad.speech_started"}
{"type":"input.vad.speech_ended"}
{"type":"input.transcript.final","text":"Hi Mini, can you help me plan today?"}
{"type":"pipeline.stage","stage":"stt"}
{"type":"pipeline.stage","stage":"llm"}
{"type":"response.started","response_id":"r1"}
{"type":"response.text.delta","text":"Start with one small step."}
{"type":"pipeline.stage","stage":"tts"}
{"type":"response.audio.start","response_id":"r1","stream_id":123}
{"type":"response.audio.end","response_id":"r1"}
{"type":"response.finished","response_id":"r1"}
{"type":"response.cancelled","response_id":"r1"}
{"type":"session.error","message":"A safe, user-facing reason"}
\`\`\`

Client→gateway binary frames: exactly 640 bytes of PCM16 LE (20ms at 16kHz); no custom header needed because direction identifies it. Gateway→client binary frames: \`[0x02][uint32 LE stream_id][int16 PCM LE samples]\`, max 3840 PCM bytes (80ms at 24kHz). The stream ID must match the preceding \`response.audio.start\` event and be unique per response. The browser discards old frames after cancellation. Never interleave output streams in the same WebSocket session.

The browser requests \`getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true}})\`. AEC capability varies by device/browser: test speaker-echo interference with real hardware. On \`input.vad.speech_started\` while Mini audio is still playing, flush the outgoing ring immediately, send \`response.cancel\` with actually heard milliseconds; the server must cancel LLM and TTS and **truncate unspoken assistant text/audio from its conversational state**. The server should also cap ongoing audio queues, detect stale turn IDs, and release the single-inference slot only after model work has stopped.

### Work scheduling on NFC

Recommend 4 independently bounded async queues/tasks:
1. **Audio capture + Silero VAD** (20ms input frames, echo-aware hysteresis, semantic pause detection; authoritative speech start/end events).
2. **Incremental local STT** (start with a tested CPU streaming English model e.g. Moonshine Voice; if absent, bounded overlapping Whisper chunks; measure WER, accent and silence guard; avoid trusting interim transcripts as final).
3. **Resident local Ollama stream** (\`llama3.2:1b\` as fallback; benchmark Qwen 0.8B/2B under same memory, no external LLM API, short clauses, grounded Friend/Mentor persona and user-consented context).
4. **Pocket TTS native stream** (cache **private** voice conditioning state, stream audio immediately as text clauses become stable, yield PCM16 24kHz frames, cancel on barge-in). If approved voice likeness is inadequate or gated weights cannot be legally downloaded, retain the existing Chatterbox fallback with honest larger latency, without pretending it is Pocket.

Use a bounded per-user turn queue and maximum 1 heavy inference at first, as current NFC worker does. Don't promise multiple simultaneous inference sessions on 8vCPU/16GiB guest without measured capacity. Keep raw reference WAVs off GitHub and off Vercel. Treat derived embedding/voice states as sensitive. Never silently persist raw audio or conversation transcripts.

## Security and release gates

- Same-origin secure WSS for public access; browser sends no NFC IP, worker token or service-role key.
- Gateway verifies Supabase Auth JWT against the actual \`Miniai\` project, checks expiry, and independently binds \`user_id\` to session, scope and memory retrieval; per-user limits; reject replay/rate abuse and unauthenticated traffic *before* microphone audio.
- Never expose \`/api/voice/live\` experimental localhost owner route publicly. The separate localhost experiment PR #4 is not a replacement for public WSS gateway.
- On setup/teardown, browser must release mic tracks and Web Audio contexts. Background/tab-hidden pages stop recording.
- Require explicit consent for personal memory; private storage uses verified \`auth.uid()\` and RLS.
- Check two actually verified user accounts sign in independently, save/list/delete *their own* facts, and fail to access each other's data. Synthetic RLS tests are useful but not the same as real sign-in evidence.
- QA: invalid/expired JWT, cross-origin WS, first message authentication timeout, duplicate sessions, 422 silence, 429 busy, 413 oversize, 1008 policy, AEC on speaker, 200 varied turns, barge-in and stale audio test, 2+ device types, friend/mentor audible likeness.
- Deployment: GitHub CI, Vercel production tag, explicit NFC worker staged rollout with rollback. No enabling \`MINI_REALTIME_GATEWAY_READY\` until end-to-end tests truly pass.

## Why not extra services?

Kyutai Unmute is a **pattern**; we can use its public event conventions and local CPU-oriented Pocket TTS, while continuing to own the user experience, prompts, private voice samples and server. Vercel now supports WebSocket Functions but the project still needs an authenticated same-origin gateway with NFC secure connectivity. Supabase is retained for identity and user memory because it already exists. No additional hosted AI inference vendors are required.

## Frontend acceptance checklist

- [x] Existing Friend/Mentor and signup UI preserved; streaming area newly integrated.
- [x] 20ms mic PCM16 frames, browser AEC requested, 24k output playback worklet.
- [x] Same-origin socket, Supabase user session required, readiness gate default OFF.
- [x] Playback receipts and barge-in output buffer truncation.
- [x] Responsive realtime states and latency measurement with no fabricated result.
- [ ] Authenticated gateway path actually running over TLS/WSS.
- [ ] NFC Silero + streaming STT + Ollama token stream + licensed custom-voice Pocket ready.
- [ ] Real verified two-user and voice tests pass.
- [ ] Vercel production deploy returns READY for reviewed main SHA.
