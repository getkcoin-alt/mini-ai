# Mini AI NFC owner pilot — Browser HTTP 429 incident

## Evidence and interpretation

The external deployment agent reported a successful NFC CLI WAV-input → faster-whisper → Ollama 1B → Chatterbox Friend voice turn (16.86 seconds) and private profile CRUD tests. The Mac browser separately observed POST /api/voice/speak returning HTTP 429. The worker's one-request semaphore rejects simultaneous expensive requests; this is intentional capacity protection, not proof of account rate limits or invalid voice cloning.

The agent report also contains two failed exit codes (1 and 2) during final synchronization/verification. The report does not explain them. Do not mark the actual browser microphone loop complete until the failures are investigated and a real browser turn passes.

## GitHub frontend fix

- A browser-local single-inference gate now serializes speak/chat/turn/sample requests.
- Playback stop no longer aborts HTTP work that continues executing on the worker.
- Stop during pending work mutes the eventual result while keeping the server busy until inference completes.
- A real server 429 is displayed as an understandable busy message, with no automatic duplicate inference retries.
- Voice action buttons are disabled during local inference and restored when the request settles.
- Cross-tab collisions can still return legitimate 429; do NOT remove the backend resource guard.

## Guest deployment — execute ONLY inside mini-ai-inference

The live guest serves the frontend from /opt/mini-ai/dist, so pulling only /home/ubuntu/mini-ai does not update browser assets. Review local changes before copying.

~~~bash
cd /home/ubuntu/mini-ai
git pull --ff-only origin main
node --check app.js
node --test tests/voice-request-gate.test.mjs
sudo cp -a app.js voice-request-gate.js /opt/mini-ai/
sudo bash scripts/build_guest_frontend.sh
# Restart Mini's service ONLY when no inference is currently active:
sudo systemctl restart mini-voice-worker
curl -fsS http://127.0.0.1:8765/api/voice/status
~~~

Do not restart libvirt, other VM guests, unrelated host applications or publicly open port 8765.

## Verification

1. Connect from Mac via existing SSH tunnel and open one tab at http://localhost:8765.
2. Test voice prompt followed by another voice button while busy: browser must avoid creating a second heavy request.
3. Test actual microphone → Whisper → Ollama → Chatterbox → browser playback, with transcript, timings and no scripted demo fallback.
4. Press Stop during inference: eventual audio should remain muted; a new turn must wait until the prior request settles.
5. Try a second tab intentionally: backend 429 remains safe and frontend should display a friendly busy message.
6. Check systemd logs, VM memory and protection of win11-thunder-rdp and ayush.

Phase 1B private CLI voice is reported working. Actual browser microphone interaction and public login flows remain distinct release gates.
