# MINI AI — SERVER AGENT EXECUTION PROMPT
## Mission: NFC modular 100% local voice inference, authenticated streaming frontend, custom Mini voices
**Read every instruction. This is an IMPLEMENT + TEST task, not merely a proposal.**

**Mandatory GO/NO-GO acceptance contract:** [PHASE-1C-MEASURABLE-ACCEPTANCE-CRITERIA.md](PHASE-1C-MEASURABLE-ACCEPTANCE-CRITERIA.md). All G0 checks are hard blockers; G1 gates invited MVP, G2 gates public beta, and G3 is a stretch target. Attach actual measurements and do not claim PASS from planned tests.

**Repository:** \`https://github.com/getkcoin-alt/mini-ai\`  
**Frontend architecture:** \`docs/MINI-MODULAR-VOICE-ARCHITECTURE.md\` on \`feature/mini-modular-realtime-frontend\`  
**Do not touch:** \`getkcoin-alt/itsmay\`, other GitHub projects, other NFC VMs, host virtualization settings, or public network ports without explicit need and authorization.

You have Linux SSH, NFC host and \`mini-ai-inference\` guest access. You must inspect the actual files, network paths, model usage terms, current Git SHA, systemd unit, resource limits, and existing deployments BEFORE making any changes. You may make implementation improvements within this scope, but you are accountable for actual results rather than unsupported assumptions.

### Non-negotiable product architecture

\`\`\`text
PWA browser / mobile web on Vercel
    │ Same-origin authenticated WSS /api/voice/realtime
    │ (verified Supabase JWT; no secrets in browser)
    ▼
Vercel lightweight WS relay (or separately secured gateway)
    │ Authenticated, encrypted upstream to private NFC guest
    ▼
NFC private mini-ai-inference VM (8vCPU/16GiB)
    ├── Silero VAD → true interrupt detection and end-of-turn
    ├── streaming local STT (benchmark Moonshine Voice or bounded faster-whisper chunks)
    ├── local Ollama stream:true (retain our real Friend/Mentor prompts + consented memory)
    └── Kyutai Pocket TTS native streaming with OUR authorized Friend/Mentor voices
          └── PCM16 24kHz chunks back to user
    ▲
    └── browser sends playback.progress; interruption cancels all stale output
\`\`\`

Eliminate **external inference vendors**. Do not use ElevenLabs, OpenRouter, hosted STT/TTS, paid endpoints, or any cloud GPU without explicit approval. Supabase remains the user identity/private-memory database, Vercel remains the UI+gateway, and NFC remains the local inference host. Kyutai Unmute is a REFERENCE architecture, not a requirement to run its entire Docker stack; its larger 1.6B GPU streaming TTS/STT is not assumed to work on our CPU guest. Do not replace our local LLM.

### A. Production-safe preflight

1. Check \`nfc\` host resources; \`virsh list --all\`; verify \`win11-thunder-rdp\` and \`ayush\` status unchanged. No changes to libvirt configuration.
2. Inside \`mini-ai-inference\` guest, check \`systemctl status mini-voice-worker\`, effective \`MemoryMax\`, CPUQuota, \`free -h\`, \`df -h\`, \`ss -lntp\`, and available model files. Preserve working Chatterbox + Whisper + Ollama 1B. Record last known green commit and rollback commands.
3. Create feature worktree and separate venv/dependencies for tests; don't install Pocket/Moonshine/Silero directly into the production worker environment until proven. Run existing tests first.
4. Keep voices only in private \`/var/lib/mini-ai/voice/\` or equivalent; mode \`0700\` directory, \`0600\` files. Do not put original WAVs, HF tokens, or any saved voice embeddings into Git, Vercel, artifact logs or shared output.
5. Check full exact official model license and permissions; the owner says both voice samples are licensed.

### B. Voice model acceptance before any swap

Kyutai Pocket TTS catalog voices \`alba\`/\`george\` already benchmarked on NFC with 152–255ms FIRST CHUNK after TEXT ready, RTF 0.46–0.87 and ~1.25–1.8 GiB RSS. Those are NOT Mini's original Friend/Mentor custom voices. Previous attempt to use arbitrary WAVs correctly failed on gated cloning weights.

- Authorized human operator must go to https://huggingface.co/kyutai/pocket-tts and accept model access terms. No bypass. On NFC authenticate model access securely as the \`mini-worker\` service identity; do not print or paste tokens to logs or git.
- Once access is granted, benchmark BOTH private \`reference_friend.wav\` and \`reference_mentor.wav\` using the precise same short phrases against resident Chatterbox. Compare Pocket \`english\` and \`english_18m_2026-10\` (other variants only if licensed/supported).
- Measure initial load, warm first chunk, per-utterance end-to-end audio, RAM, CPU usage, and blind-rated perceived voice resemblance, emotional range, pronunciation and naturalness.
- **Never** silently switch to catalog voices or invent that a sample is cloned.
- If likeness is insufficient or access has not been approved, retain Chatterbox as verified fallback and report why real-time goal remains blocked. Don't claim 500–800ms audio.

### C. Implement four bounded async stages on the NFC guest

**Stage 1: audio framing + Silero VAD**
- Take 16kHz mono PCM16 LE frames of exactly 20ms/640 bytes from \`mini.realtime.v1\` browser protocol.
- Add CPU Silero VAD with audio accumulation, hysteresis, min active-speech duration, background-noise threshold, end-of-turn pause behavior and ongoing VAD during Mini speaking (barge-in).
- Emit \`input.vad.speech_started\` and \`input.vad.speech_ended\` grounded in real VAD.
- AEC is requested on browser via getUserMedia. Test real device echo and prevent own output falsely triggering interruption. Never claim AEC guaranteed.

**Stage 2: streaming STT**
- Test Moonshine streaming CPU STT or reliable overlapping-window faster-whisper. Track stable partials/finals, bounded buffers, end-of-utterance latency, WER on English + Indian-accent speech + background noise. Retain verified faster-whisper fallback. Do not use Kyutai 1B STT on CPU until practical measured speed.
- Never send hallucinated "no speech" transcripts; return guarded 422/appropriate silent-turn event.

**Stage 3: local streaming LLM**
- Keep \`llama3.2:1b\` as safe baseline and the real Friend/Mentor system prompts. Use \`/api/chat\` Ollama \`stream:true\`, bounded completion, keep one tested small model resident within guest RAM limits. Match responses to user consented Supabase profile/facts only after the gateway has verified the authenticated user.
- Chunk at coherent clause punctuation; do not artificially delay until the full answer. Track time-to-first-token and first coherent clause, and avoid superficial generic filler.
- On interruption, close the stream and delete any *unheard* assistant text from conversation context. Never invent memories or store unconsented audio.

**Stage 4: native Pocket TTS streaming**
- Preload the **licensed custom** Pocket voice state for Friend and Mentor, not a public catalog replacement, and generate each clause in streaming chunks; resample PCM to 24kHz mono signed little-endian if needed.
- Send incremental 20–80ms output PCM chunks over secure gateway, preserving sentence boundaries and timestamps. Reserve inference slots and release only after worker is actually done (client abort alone is insufficient).
- If Pocket fails or the voice is wrong, switch to real Chatterbox fallback, label its actual latency, do not fake streaming capabilities.

Implement bounded queues and cross-stage cancellation using per-user session/turn IDs, explicit memory ceilings and backpressure. Start with one heavyweight active inference per guest. Measure RAM and CPU on 8 vCPUs/16GiB before increasing concurrency.

### D. Match the exact frontend transport contract

Read frontend repo files:
- \`mini-realtime-protocol.js\`
- \`mini-realtime-client.js\`
- \`mini-realtime-ui.js\`
- \`public/mini-capture.worklet.js\`
- \`public/mini-playback.worklet.js\`
- \`api/voice/realtime-config.js\`
- \`docs/MINI-MODULAR-VOICE-ARCHITECTURE.md\`

Browser→server: binary raw PCM16 LE 16k 20ms/640 bytes; first text event \`session.start\` must include \`protocol:"mini.realtime.v1"\` and Supabase user access token. Verify JWT BEFORE accepting microphone audio. Set \`session.ready\` only once the real user authorization and per-user capacity gate pass.

Server→browser: event JSON for \`input.vad.speech_started\`, \`input.vad.speech_ended\`, \`input.transcript.final\`, \`pipeline.stage\`, \`response.started\`, \`response.text.delta\`, \`response.audio.start\`, \`response.audio.end\`, \`response.finished\`, \`response.cancelled\`, \`session.error\`; binary frame \`[0x02][uint32 LE stream_id][PCM16 24k payload, ≤3840 bytes]\`. Unique stream ID per output response, no interleaving. Browser sends \`playback.progress\` and \`response.cancel\` with \`heard_ms\` to truncate spoken/UNSPOKEN context. Follow documented ordering exactly.

Transport endpoint is **same-origin WSS \`/api/voice/realtime\`** from the Vercel frontend. As of Oct 20, 2026 Vercel Functions support WebSocket connections. Build a tiny **verified JWT** WSS proxy or gateway using supported Node 22 runtime and \`ws\` or equivalent; do not invent a public NFC backend URL. Accept only TLS-secured authenticated upstream and keep NFC worker token on server side. Ensure system can limit connections/session duration and route connection ownership. Set \`MINI_REALTIME_ENABLED=true\` and \`MINI_REALTIME_GATEWAY_READY=true\` on Vercel **only after** actual backend and two-user tests pass. Do not enable either flag to make a demo button appear.

### E. Real auth and privacy gates (Supabase Miniai)

- Supabase project: \`gkdaxtnlwojggdqitsex\`. Verify Google OAuth and email delivery use actual provider configuration and pass real verification with **two independently owned accounts**; never fake OTPs, impersonate users or inject "verified" rows to count as sign-ins.
- Database's existing RLS protections must remain unchanged. Bind a realtime session to the verified Supabase \`auth.users.id\`. Never use browser-controlled user_id or unverified JWT metadata.
- Retrieve only consented \`mini_profiles\`, \`mini_memories\`, recent approved dialogue. Honor forget/delete/export and memory opt-in. STT audio and private voice references must not automatically be retained.
- Test cross-account negative access and forced disconnect/revocation/expired session; invalid/missing token must close safely. Per-user limits and rate limiting mandatory for public service.
- Scriwo WhatsApp OTP remains OFF until approved templates and delivery hooks are independently verified.

### F. Real acceptance tests — required proof, no fabricated "AI talking"

1. On Mac/mobile browser, sign in as verified account A, confirm its memories read/write/delete; independently sign in as verified account B; ensure A cannot query B (and vice versa).
2. Speak naturally to Mini in both Friend and Mentor via browser microphone. Capture actual VAD events, stable STT, Ollama streamed text and authorized Pocket voice PCM played by browser. Check no sample voice is emitted by fallback incorrectly.
3. During Mini speaking, **interrupt mid-sentence**. Audio stops immediately; the worker cancels token/TTS generation, releases slot when actually safe; the model's conversation excludes unheard text. Subsequent turn succeeds without 429 from stuck work.
4. Test quiet room, street noise, speaker-output echo, short silence, rapid speech, English accents, Hindi fail-safe, iPhone Safari, Android Chrome and desktop. Test 2 concurrent authenticated users with bounded queue, without memory leakage.
5. 200+ valid turns: record p50/p95 \`end_of_user_speech → FIRST MEANINGFUL AUDIO PLAYED\`, STT final, first LLM clause, first custom-voice Pocket chunk, full turn, RSS/CPU, error rate and voice likeness. Aim for 500–800ms only as an **aspirational** value. Previous full turn averaged ~13.5s; never treat Pocket's 152ms model-only first chunk as full-turn latency proof.
6. Verify production rollback, worker health and existing VMs unchanged. Keep original \`/api/voice/turn\` and Chatterbox fallback until new path is stable. No naked public port 8765.

### G. Git/release process and deliverables

- Never push directly from an old \`experiment/mini-reflex-streaming\` branch over the newer Supabase-auth main frontend. New modular branch is authoritative contract. Update backend via reviewed feature branch PR to \`getkcoin-alt/mini-ai\`, run \`npm test\` and Python tests, build frontend and keep NFC service versioned.
- Provide a **concise actual verification report** with: exact VM/commit, engine model versions, both custom-voice approvals, actual timing distributions, real two-user verification results, cross-account tests, WSS auth, audio barge-in and error-case evidence, CPU/RAM, and rollback verification. Distinguish verified vs blocked.
- If any required credential/license/config is missing, implement all safe independent pieces and identify **only** the precise human action needed. Never fabricate a success or install alternative hosted services without approval.
- Do NOT change Vercel billing or try to bypass API deployment limits. The frontend's Git production release may still face HTTP 402 daily quota. Report blocked live deployment precisely; preserve working production if blocked.

**Start by checking the actual host and repo state, then implement highest-impact safe steps. This task ends only with code, passing tests, and an evidence-backed status report.**
