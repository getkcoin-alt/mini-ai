# Mini AI private streamed-phrase pilot — NFC execution and evidence

Status: **experimental code only** (branch \`experiment/mini-reflex-streaming\` / PR #4). The live NFC worker and the public Vercel frontend have NOT been upgraded by this document. This branch was based on an earlier \`main\` before Supabase Auth was merged; DO NOT blindly copy its \`app.js\` over the production \`main\` file. Resolve the branches in review first.

## What is implemented

- A localhost-only, opt-in WebSocket route at \`/api/voice/live\`, deliberately OFF unless \`MINI_ENABLE_LIVE_WS=1\`.
- Browser microphone MediaRecorder sends binary WebM/MP4/Opus frames, and sends \`end\` after the user stops speaking.
- Server buffers max 3MB then calls existing faster-whisper on the final recording (STT is **not yet incremental**).
- Ollama emits tokens and coherent text clauses with \`stream:true\`, from the existing small local model.
- Each clause is synthesized using the original authorized **Chatterbox** Friend or Mentor reference and sent as a separate WAV, playable in a sequential browser queue.
- Stop action immediately pauses browser playback and sends cooperative cancel to the server. Chatterbox may finish its current phrase before it can free the single inference slot.
- No public \`/v1/live\` route is added, no service token is sent to the browser, no new cloud provider, no automatic memory writes.

**Honest labels:** genuine incremental LLM + phrase audio streaming with approved voice, NOT native low-level audio synthesis streaming, NOT continuous full-duplex STT, NOT subsecond guaranteed first meaningful audio.

## Preflight and local-only validation

The **connected server agent** with SSH to the new guest should:

1. Capture \`systemctl status mini-voice-worker\`, \`free -h\`, the current \`/opt/mini-ai\` source commit and service resource quotas, and \`virsh list --all\` on the NFC HOST (read-only). Do not touch the two existing VMs.
2. Review PR #4 code and compare with current main, especially \`app.js\` changes introduced by Supabase Auth. Do not replace newer production UI with older branch files.
3. Create a **separate guest working tree** from the experiment branch and build it with existing pinned Node 22. Never \`npm install\` into the live voice venv. Do not run 2 resident Chatterbox workers concurrently when RAM is low.
4. Verify the code via:
   - \`python3 -m unittest discover -s services/voice_worker/tests -p 'test_*.py' -v\` (using project environment as appropriate).
   - \`node --test tests/mini-live-client.test.mjs\`.
   - \`node --check mini-live-browser.js\` and \`node --check app.js\`.
   - \`npm ci && npm test && npm run build\` after pinning the exact lockfile; for the isolated old experiment branch, check whether npm lock exists before using \`npm ci\`.
5. Enable \`MINI_ENABLE_LIVE_WS=1\` **only on a private test instance** bound to 127.0.0.1. Keep current production worker and Vercel outside this test path. Do not open any new firewall rules. If system memory cannot support a second worker, agree a maintenance slot and run a guarded temporarily switched single worker with rollback.
6. Tunnel the private testing port through SSH to a Mac browser. Verify its HTTP status shows \`streamingPreviewReady: true\` and that the extra button **Try live phrases (private test)** appears.
7. Speak a real test sentence on the Mac. Check real Whisper transcript, streaming Ollama text events, at least one WAV phrase in the authorized voice, and browser playback with correct duration. Record each phase's timing.
8. Interrupt generation during a long response. Confirm sound stops immediately, no stale WAV is played, no memory corruption, and the 1-turn inference lock eventually releases. Verify 2nd conversation succeeds.
9. Test silence 422, too-large-audio 413, concurrent busy 429, invalid WebSocket Origin / remote IP policy-close 1008. Test both Friend and Mentor.
10. Restore original worker state if any acceptance test fails. Never claim success based on model-only benchmark or test WAV generated without a browser.

## Acceptance evidence

Provide actual completed Mac microphone → faster-whisper final transcript → Ollama **stream:true** → Chatterbox sequential WAV → Mac speaker events for both approved voices, along with time from end of speech to **first meaningful audio**, total turn, RSS, CPU, and the exact Git SHA of tested code.

Current Pocket benchmark with catalog alba/george is NOT the approved voice. Do not adopt it until Hugging Face gated access is accepted lawfully and the owner confirms the cloned Friend/Mentor likeness.

## Production release gate

Public Vercel does not support a direct private localhost WebSocket through the current proxy. For public verified-user streaming, require a separate secure WSS/WebRTC gateway, user-bound short-lived session authorization and per-user memory access; never expose the local unauthenticated WebSocket directly. Public production must not switch to this test route without such a gateway.

The authentication/memory branch was merged to \`main\` at 9164c01a64a1a08fb740e0d608ca26ae5ad3f498. The experiment is deliberately not merged to main until current auth code is reconciled and end-to-end streaming evidence is obtained.
