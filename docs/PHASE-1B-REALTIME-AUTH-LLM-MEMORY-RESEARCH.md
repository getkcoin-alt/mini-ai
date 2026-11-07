# Mini AI Phase 1B+ — real-time, identity, intelligence and memory

Research decision record: 2026-11-08. Status: proposed and benchmark-ready, NOT live. Scope: Mini AI repository only; do not modify itsmay or disrupt the working NFC guest.

## Baseline and truth boundaries

NFC pilot as reported by the user's deployment agent:
- 22 of 23 speech requests returned HTTP 200; 1 silence/no-speech rejection returned intentional HTTP 422. The sample is too small for a production reliability claim.
- Reported STT approximately 1–1.8 seconds, Ollama reasoning 4.9 seconds, Chatterbox 7.8 seconds, and complete recorded turn approximately 13.5 seconds, range 9–19 seconds.
- Both owner-approved reference voices work; guest memory reported stable around 3.1 GiB.
- These are complete WAV-turn metrics, NOT time to first meaningful sound and NOT fully duplex streaming.
- Existing profile store is single-owner only; demo email and WhatsApp verification are not production authentication.

## Discovery 1: benchmark streaming CPU voice before renting GPUs

Kyutai Pocket TTS provides CPU-oriented, reference-conditioned voice cloning and streaming audio generation. Its published claim is approximately 200 ms time to first chunk after text arrives on tested hardware; do not extrapolate to NFC's Xeon. The October 2026 release offers tiny English models around 18.2M, 6.9M and 1.9M parameters in addition to the larger English model, with substantial reported CPU speedups. Very small variants may lose voice similarity, so assess both persona voices blindly.

Pocket TTS exports reusable private voice-state data instead of reprocessing the same reference recording on every turn. The official original voice-cloning model on Hugging Face may require accepting gated-access and usage terms. Honor commercial license and explicit consent; never put reference audio, cached voice states or Hugging Face tokens in public Git.

New experimental benchmark: scripts/benchmark_pocket_tts.py. Run in a SEPARATE virtualenv on the NFC guest; do not install into the running Chatterbox service environment. Compare the English default and english_18m_2026-10 with the SAME exact phrase and the SAME owner-authorized Friend and Mentor samples. Record load time, voice-state time, first audible chunk after text is supplied, total generation, output duration, RTF, memory and subjective resemblance. If the voice sounds unlike Mini, retain Chatterbox.

Official references:
- https://github.com/kyutai-labs/pocket-tts
- https://kyutai-labs.github.io/pocket-tts/API%20Reference/python-api/
- https://kyutai-labs.github.io/pocket-tts/CLI%20Commands/export_voice/
- https://huggingface.co/kyutai/pocket-tts

## Discovery 2: streaming STT while the user is speaking

Moonshine Voice has on-device, CPU-optimized streaming speech recognition models. The current English streaming Tiny/Small/Medium model family is listed as MIT licensed. The toolkit also documents a local ZipVoice voice-cloning API, but do not assume it beats Pocket/Chatterbox without testing. Run side-by-side STT benchmarks using approved English clips: accented speech, fast speech, background noise, silence and interruptions. Compare word-error rate, time from end-of-utterance to final transcript, partial stability, CPU and RAM. Keep faster-whisper tiny.en as fallback; do not silently assume this English setup supports Hindi.

Official references:
- https://github.com/moonshine-ai/moonshine
- https://moonshine-voice.readthedocs.io/en/latest/
- https://moonshine-voice.readthedocs.io/en/latest/models/available-models/
- https://moonshine-voice.readthedocs.io/en/stable/using/text-to-speech/

## Mini Reflex: a two-speed audio architecture

This is a proposed novel COMPOSITION of standard technology, not a claim of inventing a new foundation model.

Browser microphone -> 20–40 ms audio frames -> local/server VAD + incremental STT -> verified turn endpoint -> resident streaming Ollama -> sentence/phrase chunker -> cached Pocket TTS voice state and streaming chunks -> browser audio queue, with interruption and cancellation.

The key architectural upgrade is overlap:
1. Recognize audio while the user speaks.
2. Feed the final STT input to the LLM as soon as the turn detector decides the user has finished.
3. Use Ollama chat stream=true; measure first token and first coherent phrase, not only completion time.
4. Start streaming TTS once a stable clause is available instead of waiting for the entire reply.
5. Play early audio frames via browser AudioWorklet or suitable streaming audio playback.
6. Permit human interruption: halt playback immediately, send cancel(turn_id) to worker, actually stop both LLM and TTS stream on server, and release inference slot only AFTER cleanup.
7. Only remembered words the user actually heard count as shared dialogue. A browser abort does not cancel server inference by itself; preserve request-ID/turn-ID accounting.

One can optionally play a short, clearly non-answer, locally pre-generated acknowledgment in the approved Mini voice after detecting valid speech. Do not play it on silence, do not falsely imply the AI has already answered, and DO NOT count acknowledgement time as meaningful first-audio latency.

Network: private pilot can start with authenticated WSS and current FastAPI for incremental frames while keeping HTTP /turn fallback. When mobile/WebRTC echo cancellation, ICE/TURN, adaptive barge-in and mobile jitter handling are required, prefer self-hosted LiveKit Agents rather than recreating all turn-handling algorithms. LiveKit already provides Silero VAD, turn detection, interruptions and preemptive generation. Never expose the unauthenticated localhost /api/voice aliases to the public or embed the worker master token in client JavaScript.

Sources:
- https://github.com/ollama/ollama/blob/main/docs/api.md
- https://docs.livekit.io/agents/
- https://docs.livekit.io/agents/logic/turns/
- https://docs.livekit.io/agents/logic/turns/tuning/
- https://docs.livekit.io/agents/logic/turns/vad/

## Real authentication — one provider and one user ID

Recommend Supabase Auth + PostgreSQL with row-level security. Do not ship demo OTP code 123456 or browser-stored mock identity as verified accounts.

- Google: configure real OAuth client, allowed redirect URIs, nonce/PKCE as applicable, secure browser session.
- Email: OTP or magic-link sign-in through a verified SMTP delivery source; rate-limit and expire codes.
- WhatsApp: use Supabase Auth Send SMS Hook to send Supabase-generated OTP via the verified Scriwo provider and an approved WhatsApp template. Supabase, not the browser or Scriwo, completes verification.
- Scriwo specifics (API URL, template, token, delivery status, error responses, signature) must be discovered from the REAL provider documentation or connector; never invent an endpoint or claim integration live without a delivered+verified test.
- Link identities only after ownership verification of both channels; prevent account enumeration and takeover. Normalize phone numbers to E.164. Add IP/device/user rate limits, replay protection, session rotation and logout.
- All HTTPS/WSS entry points validate real short-lived user sessions. Issue a short-lived per-user streaming token and keep master worker credentials server-side.
- Production identity and data access must never use the current single-owner SQLite row as a multi-user store.

Official sources:
- https://supabase.com/docs/guides/auth
- https://supabase.com/docs/guides/auth/auth-hooks/send-sms-hook
- https://supabase.com/docs/guides/database/postgres/row-level-security

## Better LLM — streaming without generic answers

Working baseline: llama3.2:1b (~4.9s average for full reply).

Run matched conversations on the current baseline versus Qwen3.5 0.8B and 2B (listed in official Ollama library), and optionally Qwen3.5 4B for an explicitly selected, slower deep Mentor mode. Evaluate 60+ prompts covering emotional realism, goals, accent-transcription noise, factual uncertainty, interruptions, memory fidelity, and multi-turn usefulness. Check actual supported model tags. Bigger is not necessarily more natural or faster.

Experiment with keeping one small model warm for 5–15 minutes instead of unloading on every turn, but only under guest MemoryMax with memory-pressure tests; do not assume the current 16 GiB VM can keep all models resident with 2+ concurrent users. Use stream=true, explicit turn cancellations, short spoken clauses, a bounded recent-history context, opt-in relevant facts and a separate slower research/deep-thinking mode when invited.

Source: https://ollama.com/library/qwen3.5

## Memory — what makes Mini feel personally attentive

Build per-user profile + consented facts + short recent-turn context + optional episodic summaries, each scoped to authenticated user_id.

1. Profile: nickname, Friend/Mentor style, tone, goals and boundaries, with explicit editable consent.
2. Suggested memories: e.g. Mini asks, "Should I remember that?" before saving a durable preference; never store passwords, OTPs, full voice recordings or third-party private details automatically.
3. Recent conversations: opt-in text continuity with clear retention, partial-turn cancellation hygiene and deletion.
4. Retrieval: prioritize structured facts and relevant recent history; pgvector only if retrieval quality improves measurably.
5. Privacy: real owner-based Postgres RLS for SELECT/INSERT/UPDATE/DELETE; indexing; cross-user negative tests; voice reference and reusable voice embedding treated as sensitive biometric data. Provide view, correction, export and delete-all flow.
6. Persona: Friend and Mentor access the same approved facts but generate different behavior; never make up memories.

Source: https://supabase.com/docs/guides/database/postgres/row-level-security

## Targets: explicit engineering GO / NO-GO

Targets are hypotheses for the next phase, not achieved results.

| Metric | First target |
| --- | --- |
| Speech-to-first MEANINGFUL answer sound | p50 under 2.5s; p95 under 5s |
| TTS first chunk, after text ready | p95 under 0.6s |
| STT final latency / accuracy | p95 under 1s after speech end; WER not worse on target clips |
| Barge-in stop | p95 under 250ms, no stale audio |
| Valid speech completion | >=99% of >=200 diverse attempts, with expected silent audio guards measured separately |
| Voice similarity | Both Mini voices pass blind listening over default Chatterbox baseline |
| Memory and auth | Google + email + WhatsApp OTP truly verified; no cross-account reads; profile deletion works |
| Backend stability | CPU/RSS within guest limits, 429 handled, cancellation releases resources, no ghost requests |
| Experience | High relevance, grounded responses, no generic filler and clear privacy controls |

DO NOT claim subsecond conversation based on Pocket TTS's per-text first-chunk number. Do not call Phase 1B public-ready until the actual mobile browser and identity/session tests pass.

## Ordered implementation and rollout

**Priority 0: no disruption.** Freeze the current working NFC models and scripts. Save rollback point and baseline traces. Benchmark candidates in a separate process/virtualenv, respecting the libvirt VM's 16GiB RAM and production workload.

**Priority 1: Pocket TTS A/B** with Friend and Mentor custom voices at 4 and 6 CPU threads, including the October 18M model. Compare first-chunk, RTF and voice similarity. Chatterbox remains the production default until the new provider passes.

**Priority 2: Moonshine streaming STT A/B**, with stable partial text, VAD and a Whisper fallback.

**Priority 3: stream chat and audio transport**, turn IDs, Ollama stream=true, live text chunker, streaming TTS, WebSocket AudioWorklet, barge-in cancellation and metrics.

**Priority 4: Supabase real identity**, Google + email, then Scriwo WhatsApp via verified Send SMS Hook; a production gateway must reject anonymous and expired access.

**Priority 5: per-user memory migration**, profile and verified facts, RLS, consent, edit/delete/export, safety tests.

**Priority 6: 200+ turns / 10+ invited users** across noisy environments, mobile devices, interruptions and different accents; compare latency distribution, memory, quality and cost. Expand only after meeting gates.

Status: this document and its isolated benchmark are research assets, not a claim of a new deployed model or real-time production service.
