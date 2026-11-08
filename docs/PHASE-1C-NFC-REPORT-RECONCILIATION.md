# Phase 1C — NFC agent report reconciliation (2026-11-08)

**Source:** Operator-provided NFC implementation report in chat. This record is a review of claimed measurements, not a direct authenticated inspection of the guest. **Do not mark Phase 1C INVITED MVP GO** based on this evidence.

## What the agent reported

- NFC KVM guest \`mini-ai-inference\` operating, other VMs and workloads unchanged.
- \`services/voice_worker/realtime.py\` claimed to implement private WebSocket Silero VAD → faster-whisper tiny.en → Ollama llama3.2:1b \`stream:true\` → Chatterbox Nano custom approved voice PCM frames.
- Custom Kyutai Pocket cloning failed with an explicit access-gate error. Correct fallback: do not substitute unapproved catalog voices.
- Private WebSocket smoke test reported invalid-JWT rejection, one valid recorded-audio STT/LLM/TTS turn with 55 PCM frames, and one explicit client \`response.cancel\` acknowledgment.
- Claimed CI: Python 12/12, Node 30/30, frontend built locally. These commands/logs have **not** been independently retrieved from the NFC VM.
- Claimed \`turns.valid=1\`, response onset ~6370ms, claimed TTS first PCM ~6370ms, claimed user/session count=1, claimed \`decision=INVITED MVP GO\`.

## Live connector reconciliation

| Check | Current verified finding | Consequence |
| --- | --- | --- |
| GitHub main | \`e622266e6840bf96be58e65501625de688d69478\` | Public frontend acceptance document current; operator backend SHA is different |
| Reported guest SHA | \`9a2d72904d60e8ad1753cee1a210cd22256156e2\` is **not found** in this GitHub repository through commit lookup | Guest changes may be local-only/unpushed. Require branch + PR, no blind deployment |
| Backend file in GitHub main | \`services/voice_worker/realtime.py\` is **not present** | Cannot code-review claimed NFC implementation or confirm its WebSocket security from GitHub yet |
| Vercel | Latest \`main\` SHA \`e622266e6840bf96be58e65501625de688d69478\` has a READY production deployment | Old deployment quota blocker resolved; says nothing about private NFC live streaming |
| Production public auth config | \`/api/auth/public-config\` responded 200: Supabase project \`gkdaxtnlwojggdqitsex\`, enabled true, WhatsApp disabled | Public config wired. Does not prove Google OAuth or email OTP delivery |
| Production realtime config | Direct protected deployment fetch got a deployment-authentication-required response | Cannot claim public realtime WSS handshake/relay verified from this check |
| Connected Miniai auth.users | Count **0** (also confirmed_email=0, confirmed_phone=0, signed_in=0) | Contradicts agent's \`real_verified_users:1\`; require exact project binding and real account verification evidence, without exposing identifiers |
| Safety checks | One invalid token rejection, one attempted cancellation in operator report | Far below 40 auth negative tests and 30 barge-in tests; not proof of full-duplex barge-in from microphone |

Do not record or repeat unrelated services or unrelated API credentials from the operator report.

## Phase 1C G0/G1 evaluation

- **G0 two real verified users: BLOCKED.** Live connected project has zero Auth users. Agent's one-user report conflicts with this project, and two independent browser sign-ins were not shown.
- **G0 privacy: NOT VERIFIED.** A local/global **SQLite** profile reportedly feeds the LLM. Do not allow per-user Mini memory on that owner-only store. Wire worker context by verified Supabase \`user_id\` with per-user RLS and negative cross-account tests.
- **G0 actual browser-to-speaker: NOT VERIFIED.** Private WebSocket smoke tests with input audio and generated PCM frames are valuable but not an observed human microphone → gateway → real browser speaker loop for both personas.
- **G0 approved voices: PARTIAL.** Chatterbox references are present and permitted; custom Pocket voice model unavailable. No blind listening study or owner's side-by-side approval of streamed output was provided.
- **G0 interruption: NOT VERIFIED.** One explicit client \`response.cancel\` returning \`response.cancelled\` is not proof that microphone-triggered Silero barge-in stops audible playback, truly cancels inference and truncates unheard memory. p95 from one trial is statistically meaningless.
- **G1 reliability: NOT VERIFIED.** 1/200 valid-turn sample size, no p95 distribution.
- **G1 meaningful audio latency: FAIL for reported single turn vs 4.0s median threshold, but no statistically valid p50/p95.** 6370ms is a single measured/reported turn, not a distribution; may be server-side not actual first played speaker audio.
- **G1 custom TTS first PCM: FAIL if reported 6370ms is time from the first stable LLM clause, but this measurement's definition needs checking.** It must be timed clause-ready → first emitted 24k PCM; do not conflate it with end-of-speech-to-first PCM.
- **G1 CPU: promising but under-sampled.** Reported 2.1GiB peak RSS and 7.8GiB guest available, but no 45-min soak/concurrent-user evidence.
- **Overall decision: BLOCKED.** Safe inference prototype exists per agent report; no authenticated public two-user release until actual end-to-end evidence passes G0 + G1.

## Next required agent deliverables, in order

1. Preserve active worker; identify exact \`mini-ai-inference\` Git status. Push \`realtime.py\`, tests, service changes and requirements to a reviewable branch/PR in \`getkcoin-alt/mini-ai\`. Run/attach actual Python and JS CI logs and capture the SHA of what is running. Never rewrite \`main\` from a stale branch.
2. Audit source of JWT validation and memory: confirm exact Supabase project, resolve why the connected Miniai project's \`auth.users\` has zero users, and replace single-owner SQLite LLM context with independently account-scoped consented memory. Test two actual verified accounts (do not inject fake verified users).
3. Verify public signed-in HTTPS/WSS session from Vercel through secure gateway to NFC. A private localhost \`/api/voice/realtime\` handler is not proof of the production WSS relay; do not expose the raw worker or passwords to the internet.
4. Record 10 live microphone-to-speaker turns **per persona** on real browser/devices, then ≥200 valid turns with latency distributions. Record \`speech_end→first meaningful played audio\` p50/p95, plus independent \`clause_ready→first custom-voice PCM\`.
5. Execute ≥30 real Silero-triggered barge-in tests and ≥40 authentication rejection tests, with server cancellation/lock-release and heard-only context truncation proof. Test missing, expired and cross-user JWTs and simultaneous session isolation.
6. Keep Chatterbox fallback. Accept Pocket voice-cloning model access via official Hugging Face user action and benchmark voice likeness **before** enabling its custom streaming mode. Do not use catalog voices as the custom Mini persona.
7. Produce exact G0/G1 PASS/FAIL/BLOCKED report against [Phase 1C measurable acceptance criteria](PHASE-1C-MEASURABLE-ACCEPTANCE-CRITERIA.md). Leave public stream flags OFF until all release gates pass.

**Decision:** GitHub frontend and private NFC streaming smoke reports are progress; they are not evidence for \`INVITED MVP GO\` yet.
