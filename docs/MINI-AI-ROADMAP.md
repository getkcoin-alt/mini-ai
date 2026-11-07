# Mini AI — product delivery roadmap

> **Single source of truth for the feature sequence.** Updated: 2026-11-07.  
> Source repository: \`getkcoin-alt/mini-ai\`. Reference engine: \`getkcoin-alt/itsmay\` (read-only in this phase).
>
> **Current state:** Interactive **frontend-only concept**, not production authentication or a connected AI voice service. A checkbox indicates a deliverable is actually present, not merely designed.

## North star

A low-latency, voice-first personal AI that can feel like a warm best friend or a practical mentor, understands human language, learns **with permission**, eventually works with a phone-connected physical device, and does not pretend to be human.

The competitive advantage is **trustworthy continuity + personal relevance + dependable action**, not trying to outtrain frontier models. Five delightful, reliable interactions beat 50 speculative capabilities.

## Boundary between the two repositories

- \`mini-ai\` owns Mini's new user-facing app: graphics, signup/onboarding UI, personal connection design, voice UI, mobile UX, hardware pairing UX and Mini-specific client code.
- \`itsmay\` retains the other programs and shared engine code; nothing from that repository is copied or deleted in Phase 1. Its \`core/companion\`, prompt files, SQLite memory, voiceprint, Ollama, faster-whisper and Piper implementations are reference material for **future backend adapters**, not currently connected to this frontend.
- Scriwo is the proposed production WhatsApp OTP provider; secrets and verification must stay on a trusted server, not in this frontend.
- Vercel hosts the lightweight public frontend only; it does **not** host an always-on local Ollama/Piper/Whisper instance.

## Phase 1A — graphic-led, interactive frontend prototype (current)

- [x] Responsive identity system, organic animated face/orb, voice-wave and breathing animations; reduced-motion preference.
- [x] Welcome graphics with clear Friend/Mentor story and mobile app-style navigation.
- [x] Google sign-in entry design with honest "not connected" disclosure.
- [x] Email sign-in and six-digit verification **simulation**, visibly marked demo with \`123456\`.
- [x] WhatsApp number and OTP **simulation**, labeled Scriwo server integration **later**.
- [x] Six-step Mini-led onboarding that asks natural questions: the user's name; Mini's nickname; best friend/mentor/both; conversational tone; current focus; personal boundaries.
- [x] Answer by keyboard and, **when browser support and permission allow**, speech recognition. Mini speaks questions via browser speech synthesis.
- [x] Show a formatted, editable preview of the profile signal. **Not an LLM transformation** yet.
- [x] A transparent **profile-sync percentage** calculated from answered questions and a trial conversation, not from hidden "AI understanding" claims.
- [x] A voice-first companion screen with Friend/Mentor switch, browser STT/TTS where supported, captions, interruption/stop control, and honest scripted responses.
- [x] My Mini/profile editor, planned Memory and Hardware screens, consent-conscious controls and local preview reset.
- [x] Local storage for onboarding preferences only; no remote account, real identity verification, persistent AI memory, voiceprints or cloud recordings.
- [ ] Manual testing on Android Chrome, iOS Safari, desktop Safari and desktop Chrome. Unsupported browsers must gracefully fall back to typing.
- [ ] End-to-end production identity and backend are **out of scope** until Phase 1B.

### Working prototype acceptance

1. A new user sees the graphic-led landing page, selects a sign-in method, and can enter demo onboarding without claiming verification.
2. Six questions can be answered, skipped, revisited and edited; spoken input works on supported browsers with permission.
3. The progress percentage is deterministic and responds to completed profile facts; no duplicate farming or artificial emotional pressure.
4. The companion renders a voice-first interaction, toggles between Friend/Mentor, and clearly labels its responses as scripted.
5. Mobile width 320px+ has large microphone affordance, bottom navigation, readable typography and no horizontal scrolling.
6. "Memories" and "Devices" honestly show coming-soon states. No hardware or cloud account is falsely shown as connected.

## Phase 1B — first **real** AI MVP (implement in this order)

- [ ] **1. Secure identity gateway:** Google OIDC using auth-code/PKCE, email magic link or server-verified OTP, and WhatsApp OTP via Scriwo server-to-server flow with abuse/rate limits, expiry, resend rules, consent and verified phone binding.
- [ ] **2. Per-user tenant isolation:** One user ID per person; companion nickname, mode, profile, chat sessions and memory partitioned by authenticated user. No shared tenant data.
- [ ] **3. Streaming voice path:** microphone -> VAD -> streaming STT -> LLM -> incremental TTS -> speaker; interruptible playback and clear mic permission controls. Target perceptible responsiveness; measure actual first-audio and turn latency before claiming metrics.
- [ ] **4. Low-cost development stack:** use existing itsmay-supported **Ollama llama3.2:3b**, **faster-whisper**, **Piper** and optional speaker ID on a trusted GPU/CPU worker. These are open/local components, not an unlimited free public hosted voice API. The mobile/web client talks to a secure gateway.
- [ ] **5. LLM-guided onboarding:** ask one question at a time; extract candidate structured facts and human-readable summaries; user **approves or edits** before any memory is saved. Model output must be treated as untrusted.
- [ ] **6. Real consented memory:** encrypted memory storage, confidence/source/time, inspect/edit/delete/export and explicit confirmation for sensitive facts; per-user isolation and voiceprint opt-in.
- [ ] **7. Real Friend and Mentor orchestration:** retain independent principles from \`itsmay/core/brain/prompts/system_mini*.md\` and \`core/companion/persona.py\`; shared memory but different response styles; guard against false actions and hallucinations.
- [ ] **8. MVP health metrics:** signup completion, time to first spoken reply, session reconnect, STT errors by browser, successful interrupt, helpfulness, second-week return use, memory correction rate and cost per voice minute.
- [ ] **9. Security testing:** device/session revocation, request quotas, OTP abuse, prompt injection, data separation, speech privacy notice, accessibility and age-appropriate protections.

## Phase 2 — user-relevant assistant action

Only expand when the real voice loop, trust controls and retention work.

- [ ] **10. Calendar + reminders** (user-granted permissions, action confirmation).
- [ ] **11. Web search and cited research** with trusted source display and injection resistance.
- [ ] **12. Documents, images and camera** with per-session permissions and clear upload/retention policies.
- [ ] **13. Email, files and approved tools** with least privilege, draft/confirm-before-send and activity logs.
- [ ] **14. Translation + offline fallback** for selected languages, with measured language quality.
- [ ] **15. Cross-device session continuity** using device-bound tokens and encrypted sync.

## Phase 3 — physical Mini

- [ ] **16. Native mobile app shell** (needed for reliable background microphone, Bluetooth routing, push and native OS permissions; web platform coverage varies).
- [ ] **17. Hardware discovery and secure pairing** (BLE for discovery/control where appropriate; use OS-supported Bluetooth audio/LE Audio routes instead of assuming BLE GATT can carry arbitrary live voice).
- [ ] **18. Device trust, ownership, revoke and firmware authenticity**; no silent always-on recording.
- [ ] **19. Wake-word, on-device VAD, offline command set and optional on-device small model** after hardware profiling.
- [ ] **20. Seamless phone ↔ wearable ↔ desktop handoff**, explicit indicator when microphone is active.

## Eleven requested capabilities: exact delivery map

| Capability | Prototype UI now | First real implementation | Longer-term extension |
| --- | --- | --- | --- |
| 1. Natural voice & text | **Partial**: browser STT/TTS and typed fallback, scripted answers | Phase 1B streaming LLM speech pipeline, barge-in | Accent adaptation and automatic speech |
| 2. Multimodal I/O | Not connected | Phase 2 images, docs and camera upload | Live video and simultaneous multimodal context |
| 3. Persistent memory | **Partial**: local demo profile only | Phase 1B consented backend memory | Rich episodic + semantic recall |
| 4. Deep apps & OS | Not connected | Phase 2 calendar, mail and files | Native OS agent actions, never bypass permissions |
| 5. Cross-device sync | Not connected | Phase 2 secure identity and session sync | Phase 3 phone/vehicle/glasses/earbuds |
| 6. On-device/edge | Reference architecture only | Phase 1B self-hosted worker for development | Phase 3 phone and hardware inference |
| 7. Browsing & agentic tasks | Not connected | Phase 2 browsing with citations and confirmations | Multi-step actions and reliable recovery |
| 8. Deep research | Not connected | Phase 2 source-grounded PDF/web reports | Multi-source spreadsheet and research workflows |
| 9. Content & code creation | Not connected | Phase 2 connected text/doc/code tools | Rich media generation and local builders |
| 10. Live translation | Not connected | Phase 2 language pipeline | Conversation-grade simultaneous speech translation |
| 11. Smart home & IoT | **Visual only**: device concept | Phase 3 approved integrations | Local IoT automations with explicit control |

### Differentiators to invest in after reliability is proven

- **Two related personalities, one trustworthy memory:** Friend listens warmly; Mentor acts as a candid accountability partner. Switching never changes the owner's data boundaries.
- **The "you meant" moment:** speak a messy thought, let Mini produce a brief candidate understanding, then correct or confirm it before it is remembered or acted on.
- **A relationship without dark patterns:** no forced streaks, fabricated awareness, false empathy, or locked basic tools. Progress measures *profile completeness*, not a monetized attachment score.
- **Auditability:** Mini can explain which remembered preference influenced a suggestion and can forget it on demand.
- **Hardware-first UX:** one voice session, identity and permission contract that will survive future device changes.

## Product risks & release gates

- SpeechRecognition availability, latency, accents and privacy differ by platform; browser speech may use vendor services. Do not call it on-device/offline by default.
- A public static Vercel frontend **cannot** safely validate Google identity, email codes or Scriwo OTP, and does not replace a GPU inference service.
- Audio devices need explicit microphone permission and a clear recording indicator. Any future "observe mode" requires truly informed opt-in and reasonable retention controls.
- Before collecting real profiles, ship a privacy policy, retention policy, age-appropriate onboarding, security review and deletion endpoints.
- Before hardware sales, validate Bluetooth/OS capabilities, battery, audio path, manufacturing, certification and accessibility.

## Build sequence rule

Do **one vertical slice at a time**: implement → test on real devices → observe failures → fix → measure retention → only then unlock the next roadmap checkbox. Do not label planned features as live.
