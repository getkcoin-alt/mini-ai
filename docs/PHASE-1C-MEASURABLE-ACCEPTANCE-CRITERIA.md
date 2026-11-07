# Mini AI Phase 1C — Measurable Acceptance Criteria

**Version:** 1.0 — 2026-11-08  
**Status:** Proposed release contract, NOT a claim that the backend has passed  
**Applies to:** \`getkcoin-alt/mini-ai\` only, including production Vercel frontend and NFC \`mini-ai-inference\` guest. Do not alter \`itsmay\` or existing unrelated NFC VMs.  
**Architecture:** Silero VAD → CPU streaming STT → local Ollama LLM → licensed custom-voice Kyutai Pocket TTS → authenticated WSS/PCM browser playback; Chatterbox retained as quality fallback.  
**Decision owners:** product owner accepts voice likeness; engineering owner signs test evidence and deployment readiness.

## Release classification — no blending targets with measurements

| Gate | Meaning | Decision |
| --- | --- | --- |
| **G0: Functional/security** | Two real verified accounts, secure memory isolation, correct custom voices, full microphone-to-speaker loop and barge-in all demonstrated | **Required** before ANY externally accessible voice pilot |
| **G1: Invited MVP** | G0 + reproducible latency, reliability and resource thresholds on NFC | Required before inviting pilot users |
| **G2: Public beta** | G1 + stronger latency/quality, two-user load behavior and operational reliability | Required before turning on public streaming flags |
| **G3: Stretch** | 500–800 ms first-meaningful-audio goal on actual approved Mini voices | **Aspirational, NOT an automatic G1/G2 release blocker** |

The initial user-reported NFC baseline was ~13.5 s average full recorded speech turn (STT ~1–1.8 s, Ollama ~4.9 s, Chatterbox ~7.8 s). Pocket TTS's 152–255 ms first-chunk benchmark used **catalog voices** (\`alba\`/\`george\`), not the authorized Friend/Mentor samples. These are historical agent-reported results, not fresh proof.

## Acceptance test conditions — reproducibility

- **Hardware:** real \`mini-ai-inference\` guest, 8 allocated vCPUs, 16 GiB RAM, CPU-only; record exact CPU, kernel, model checkpoint, weights license, Ollama version, Python venv, Git SHA, worker flags, systemd quotas, and environment. Do not benchmark while silently sharing cores with competing tests.
- **Browsers:** latest available iPhone Safari and Android Chrome plus Mac/desktop Chrome over normal HTTPS/WSS. At least one real handset each, not desktop responsive simulation alone. Report device model, browser, AEC capabilities and network type.
- **Network:** record browser→gateway→NFC RTT (median/p95) and packet loss separately. Primary performance sample: stable network RTT ≤100 ms; secondary test: 150–250 ms RTT, 1–2% packet loss and a reconnect. Do not silently discard slow failures.
- **Corpus:** ≥200 **valid spoken response turns**, with ≥70 Friend clean, ≥70 Mentor clean, ≥30 accented/noisy and ≥30 deliberate interruptions (mix across persona and devices). Also run ≥30 extra silence/echo-only turns, ≥40 negative auth attempts and ≥20 wrong-account access attempts; keep these outside valid-turn latency denominators.
- **Instrumentation:** monotonically timed \`speech_end\`, VAD start/end, STT partial/final, LLM first token/first stable clause, TTS first PCM generated, gateway first output packet, browser first **played** answer audio, played milliseconds, cancellation, completion/error, peak RSS and CPU. Keep session_id and turn_id pseudonymous and never log raw audio, OTP, JWT or personal memory text.
- **Evidence:** export per-turn machine-readable measurements (anonymized JSONL/CSV), pass/fail summary with sample size and p50/p95, build logs, exact deployed code SHA, owner listening results and rollback instructions. A response transcript or a generated WAV alone is not end-to-end proof.

Latency is measured from the **actual end of the user's spoken words** to the first **meaningful AI answer sample played by the browser audio renderer**. It includes turn-detection tail, final recognition, LLM, voice synthesis, network and playback buffering. An acknowledgement/hum, TTS first chunk measured after text is already available, a silent player-start callback, or the first text token does **NOT** count. For best accuracy, align recorded input/output waveforms on the test device; label AudioWorklet onset as a proxy when physical loudspeaker capture is unavailable.

## G0 — Hard functional/security blockers (100% required)

| ID | Requirement | Exact pass condition / evidence |
| --- | --- | --- |
| G0-01 | **Real independent identity** | ≥2 distinct human-owned accounts successfully complete **real** Supabase Google OAuth and/or email OTP/link verification (test both Google and email paths), obtain separate validated user/session IDs, sign out and back in. No injected \`auth.users\` rows or mock OTP count. Wrong/expired codes rejected. WhatsApp optional and must remain disabled until real Scriwo delivery/verification is tested. |
| G0-02 | **Zero cross-account memory leakage** | For A and B, consented profile/fact create, read, update and delete succeed only for owner. ≥20 cross-user read/update/delete and conversation/message injection attempts return no other user's data and make no mutation. Check in Supabase and via normal browser API. |
| G0-03 | **Authenticated gateway** | HTTPS/WSS same-origin client; gateway verifies signed-in user and token expiry **before accepting any mic frames**. 100% of ≥40 missing, malformed, expired, wrong-audience, cross-origin or replay tests denied with safe close/error; private NFC IP, service-role key and worker master secret never appear in JS, URLs or logs. |
| G0-04 | **Wire protocol correctness** | \`mini.realtime.v1\` uses 16kHz mono signed PCM16 mic frames, exactly 20ms/640 B; output 24kHz mono PCM16 in frames ≤80ms/3840 B plus 5 B header (type 2, uint32 LE stream ID). Pass ≥5,000 input and ≥1,000 output frames with zero malformed ordering or stale-stream playback after cancel. |
| G0-05 | **Actual speech-to-speech** | At least **10 complete live browser microphone → Silero VAD → real local STT → Ollama stream:true → approved Mini voice synthesis → browser speaker** turns for *each* Friend and Mentor. No prerecorded demo, catalog voice substitution or browser SpeechSynthesis counted. |
| G0-06 | **Authorized voice ownership/fidelity** | Use only approved 10s+ reference recordings and checkpoints with recorded model/weight usage permission. For *each* voice, ≥5 blinded listeners evaluate ≥10 varied spoken clips; mean naturalness **≥4.0/5**, and ≥80% identify the same expected voice across comparison trials versus the authorized sample. Product owner explicitly accepts. If Pocket fails or is gated, Chatterbox remains fallback and Pocket streaming cannot be marked passed. |
| G0-07 | **Interruption behavior** | Across ≥30 spoken barge-in tests, browser audio stops within **250 ms p95** of actual VAD speech-start event; zero stale output after \`response.cancel\`; no unspoken assistant text inserted into user-visible/history context; server cancellation actually ends model work, not just frontend playback. Next turn succeeds with lock released. |
| G0-08 | **Consent, cleanup, privacy** | No raw conversation audio retained by default. Confirmed per-user memory only after explicit consent; inspect/delete individual memory, delete account profile and sign out; no third-party inference calls. After user stop/logout/background navigation, mic tracks close ≤1 second in 100% of 20 cases; session and buffers cleared. |
| G0-09 | **Safety and fail closed** | Silence correctly rejected (no confident fake transcription), oversize audio guarded, bounded queues prevent OOM; gateway unavailable = UI says offline and no pretend conversation. \`MINI_REALTIME_ENABLED\` and \`MINI_REALTIME_GATEWAY_READY\` remain false until server passes G0/G1. Existing HTTP \`/api/voice/turn\` and Chatterbox path stay functional. |
| G0-10 | **No server collateral damage** | NFC \`win11-thunder-rdp\` and \`ayush\` VM configuration/states unchanged; current worker has rollback configuration; no publicly exposed unauthenticated \`:8765\` port or private audio file. Production deployment includes exact reviewed SHA. |

G0-07 stop threshold is from **detected interruption**; separately record detection delay from actual mouth speech to avoid a fast UI timer masking a slow VAD decision. If response cancellation cannot interrupt the active inference kernel immediately, explicitly report the true server cleanup time and mark G0-07 blocked until bounded cleanup is proven.

## G1 — Invited MVP quantitative thresholds

| ID | Metric | Target | Measurement |
| --- | --- | --- | --- |
| G1-01 | **First meaningful answer audio** | p50 ≤ **4.0 s**, p95 ≤ **8.0 s** | ≥200 valid turns, end of actual speech → browser renderer plays meaningful PCM, **approved Friend/Mentor voice**. Show per-persona and per-device distribution. |
| G1-02 | **Valid-turn completion** | ≥**99%** (at most 2 unintended failures / 200) | Valid non-silent turns produce a grounded audio answer or explicit safe user cancellation, with protocol complete; intentional silence 422 and deliberate user cancellations reported separately. Do NOT classify unexpected 429/timeouts as success. |
| G1-03 | **Voice TTS first PCM** | p95 ≤ **0.8 s** | Measure from first stable LLM text clause available to first custom-voice PCM bytes emitted by Pocket. Separate from G1-01; Chatterbox fallback measured independently. |
| G1-04 | **VAD** | p95 speech-start detection ≤**250 ms** after annotated speech onset; p95 speech-end event ≤**700 ms** after annotated end | Hand-label ≥60 clean/accented/echo clips. Zero false user-speech start events in ≥30 AI-speaker-only/silence clips. |
| G1-05 | **STT accuracy** | WER ≤**15%** clean English, ≤**25%** noisy/accented English; p95 final transcript ≤**1.5 s** after VAD end | ≥40 independently transcribed short utterances per condition. Specify model and evaluated language. Hindi must be explicitly labeled unsupported/fallback until tested, not silently hallucinated. |
| G1-06 | **LLM responsiveness & factuality** | p95 first coherent clause ≤**3.0 s** after final transcript, ≥**85%** useful-reply pass rate | ≥60 blinded rubric-graded Friend/Mentor prompts and multi-turn followups, including 20 unconfirmed-memory probes; no invented user memories. Record local model tag. |
| G1-07 | **Stable cancellation** | p95 server-side stop/lock release ≤**2.0 s** after \`response.cancel\`; no leaked inference slot | ≥30 mid-generation interruptions, worker logs and next-turn completion, while maintaining browser stop threshold G0-07. |
| G1-08 | **CPU/RAM** | Resident voice/LLM worker peak RSS ≤**8 GiB**, guest available memory ≥**2 GiB**, zero OOM kills/restarts | 45-minute two-account alternating session soak on actual 8 vCPU/16 GiB guest; record peak memory/CPU and guest+host load. Keep configured service resource quotas. |
| G1-09 | **Two-user contention** | Two verified sessions connect safely; only one heavyweight turn runs at a time initially; second receives bounded queue or explicit **429/Retry-After**, never hangs or leaks context | ≥20 A/B overlapping speech requests. No false claim of 2 independent full-speed simultaneous inference turns. Queue policy and timeout documented. |
| G1-10 | **Mobile experience** | No horizontal overflow at 360–430px widths; all primary controls touch-sized (≥44×44 CSS px); button/state feedback ≤200ms; microphone permission denial leaves usable UI | Real iPhone Safari, Android Chrome and desktop Chrome; 10 repetitions/device; background/logout mic cleanup. |
| G1-11 | **Regression & recovery** | \`npm ci\`, \`npm test\`, \`npm run build\`, Python tests and voice smoke suite all green. Voice fallback healthy and rollback drill ≤**10 min** | Exact green CI URL, verified NFC guest unit status, Git SHA and documented rollback on staging. |

A G1 failure blocks inviting additional MVP users even if the feature flags can be set. Required security failures are blockers regardless of performance.

## G2 — Public beta and multiuser hardening

All G0/G1 criteria remain mandatory. Stronger public targets after invited-pilot evidence:

- **First meaningful audio:** p50 ≤**2.5 s**, p95 ≤**5.0 s** for each persona on tested reference-class devices; report slow-network results separately.
- **Turn reliability:** ≥**99.5%** over ≥**1,000** valid turns on ≥3 separate days, with no unhandled process OOM/restarts or corrupted conversations.
- **Concurrent authenticated sessions:** safely handle ≥**5 connected** users with a documented bound on simultaneous heavy inference; at least 2 users can alternate 20-turn conversations without cross-account leakage, starvation, or indefinitely blocked queue.
- **Latency under contention:** p95 first meaningful audio ≤**8 s** when one additional user is waiting; if the CPU guest cannot sustain this, advertise limited/private beta capacity instead of declaring public general availability.
- **User controls:** explicit memory consent, export and deletion tested on both real users; verified sign-out invalidates access for new voice connections. Session timeout, rate limits and active-call duration caps enforce policy.
- **Operational protection:** health probes, privacy-safe error tracking, 5xx/429 dashboards, SLO alerts, daily usage ceiling, rollback documented and tested. No exposed direct NFC worker endpoint.
- **Deployment evidence:** Vercel production \`READY\` at **the reviewed main commit**, HTTPS/WSS handshake tested from external browser, Supabase config correct, no 404 on \`/api/voice/realtime-config\` (unauthenticated should return 401), and gateway flags enabled **only after** staging and public-boundary tests.

## G3 — Experimental 500–800 ms goal (not a promised result)

To claim **“500–800 ms natural response”**:
- On ≥200 real approved-voice utterances on NFC and the same browser/device test route, p50 **≤800 ms**, p95 **≤1,500 ms** for *actual speech end → first meaningful audio played*.
- p95 custom TTS first chunk after first stable clause **≤400 ms**; STT and LLM timings separately measured; interruption pass G0-07; neither shorter generic responses nor unauthorised catalog voice are accepted shortcuts.
- Replicate median/p95 across Friend and Mentor. Publish actual result even if it remains 3–8 seconds; never describe a TTS-only 152 ms first-chunk as subsecond end-to-end.
- If CPU hardware cannot meet the latency goal, do not compromise fidelity or security. Flag **G3 not achieved** and provide specific measured bottleneck and resource/cost recommendation.

## Release decision rubric

| Outcome | Required evidence | Action |
| --- | --- | --- |
| **BLOCKED** | Any G0 failure; unsafe access; wrong speaker; unverified two-user auth; no end-to-end voice; or missing production backend | Feature flag OFF; keep working private voice |
| **INVITED MVP GO** | All G0 + all G1 passed with proof, reviewed code & rollback | Enable only for named invited users through authenticated gateway |
| **PUBLIC BETA GO** | All G0 + G1 + G2 passed and reviewed production SHA deployed | Roll out gradually; retain fallback |
| **G3 ACHIEVED** | Independent benchmark meets additional stretch thresholds | May market the *measured* latency with test scope stated |

**No partial pass may be represented as general production readiness.** A green GitHub build proves code health; a synthetic RLS test proves row isolation for those simulated cases; a Pocket catalog TTS benchmark proves neither authorized-voice quality nor live speech-to-speech.

## Required agent handoff format

Report a simple table with ID, PASS/FAIL/BLOCKED, measured result, sample size, benchmark timestamp, source artifact/log URL, release SHA, and explanation for every failure. Record:

\`\`\`json
{
  "git_sha": "actual tested commit",
  "server": "mini-ai-inference",
  "models": {"vad":"...", "stt":"...", "llm":"...", "tts":"..."},
  "voices": {"friend":"owner-approved true/false", "mentor":"owner-approved true/false"},
  "auth": {"real_verified_users":0, "cross_account_denials":0, "negative_auth_tests":0},
  "turns": {"valid":0, "success":0, "invalid_silence":0, "unintended_failures":0},
  "latency_ms": {"speech_to_meaningful_playback_p50":null, "speech_to_meaningful_playback_p95":null,
                 "stt_final_p95":null, "llm_first_clause_p95":null, "custom_tts_first_pcm_p95":null,
                 "barge_in_playback_stop_p95":null, "server_cancel_release_p95":null},
  "resources": {"peak_worker_rss_gib":null, "min_guest_available_gib":null, "oom_kills":0},
  "security": {"cross_account_leaks":0, "unauthorized_audio_accepted":0, "secrets_exposed":0},
  "deployment": {"vercel_production_ready_sha":null, "gateway_verified":false, "nfc_worker_healthy":false},
  "decision": "BLOCKED | INVITED MVP GO | PUBLIC BETA GO",
  "blockers": []
}
\`\`\`

All \`null\` fields mean **not measured**, never zero or a pass. Raw user audio, access tokens, secret keys, reference WAVs and private transcripts must not be attached to reports.

**Related implementation contracts:** [modular architecture](MINI-MODULAR-VOICE-ARCHITECTURE.md) and [NFC agent implementation prompt](NFC-MODULAR-VOICE-AGENT-PROMPT.md).
