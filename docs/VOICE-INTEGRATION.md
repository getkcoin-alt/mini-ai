# Mini AI — Own voice, no ElevenLabs runtime

Updated 2026-11-07. Source: [ElevenLabs voice-clone export policy](https://elevenlabs.io/docs/help-center/product/voices/voice-cloning/can-i-export-my-voice-clones) and [Chatterbox source/usage](https://github.com/resemble-ai/chatterbox).

## What works and what still needs setup

The Mini frontend now has a **voice reference upload**, a local-model status indicator, a voice test button, and a microphone turn interface. The repository contains a private Python voice worker implementing **faster-whisper → Ollama llama3.2:3b → Chatterbox**.

**Not yet running on Vercel:** Vercel cannot execute these large GPU models itself. A private worker needs to be started separately, and a reference recording must be provided by the voice owner. The production Vercel instance shows "worker offline" until configured. No model is downloaded or installed by the browser.

## Can the original ElevenLabs voice be exported?

**No.** ElevenLabs explicitly says cloned voices cannot be downloaded as standalone models or voice weights. A voice created there can be reconstructed locally only from recordings that you have the right to reuse. If this is a designed/synthetic ElevenLabs voice, use an authorized clean audio export/example; if it is your recorded voice, preferably use the original recording supplied for the clone. Similarity will vary. Respect the platform's output licensing terms and the voice owner's permission.

**No ElevenLabs API key, ElevenLabs Agent, ElevenLabs model weights, or per-character ElevenLabs billing is used by this Mini AI speech pipeline.**

## Private local workstation setup (GPU recommended)

1. Install Node.js 22, Python 3.11, ffmpeg, and [Ollama](https://ollama.com/).
2. From this repository root, build the Mini frontend:

   ```bash
   npm install
   npm test
   npm run build
   ```

3. Install a Python 3.11 virtual environment with the *correct* PyTorch + Chatterbox dependencies for your CPU/GPU. Do not blindly install CUDA wheels on macOS:

   ```bash
   python3.11 -m venv .venv
   source .venv/bin/activate
   python -m pip install -U pip
   pip install -r services/voice_worker/requirements.txt
   ```

4. In a second terminal start local Ollama and pull the small free reasoning model:

   ```bash
   ollama serve
   ollama pull llama3.2:3b
   ```

5. Start Mini's local worker + website:

   ```bash
   python -m uvicorn services.voice_worker.app:app --host 127.0.0.1 --port 8765
   ```

6. Open **http://127.0.0.1:8765**. Continue in demo mode; open **Preferences**. The voice section should report *Local worker running*. Upload a 5–20-second clean voice example, check the permission confirmation, and tap **Use this voice for Mini**. Test the generated voice. Your original reference is saved only on the private worker under `~/.mini-ai/voice/reference.wav` (override with `MINI_VOICE_DATA_DIR`).

7. In **My Space**, tapping the microphone records up to 12 seconds; tapping again sends the segment through Whisper, Ollama and Chatterbox. This is a **turn-based voice prototype**, not yet continuous full-duplex speech. You can stop playback or type an answer.

On a CPU-only machine, the Chatterbox Nano English model is selected. On a GPU, Turbo English is preferred. For Hindi, Chatterbox Multilingual V3 is selected. Model weight downloads, execution, VRAM requirements and latency depend on hardware; confirm them on your target machine. The upstream research code was archived in August 2026 and is no longer maintained, so pin/test weights before distributing an app.

## For private mobile/Vercel access later

In Vercel project `mini-ai`, set `GOOGLE_CLIENT_ID`, `MINI_OWNER_EMAIL`, `MINI_SESSION_SECRET`, `MINI_WORKER_URL` (HTTPS), and `MINI_WORKER_TOKEN` (random 32+ characters). Set that same token on the voice worker (e.g. environment), and expose it only using a secure, trusted HTTPS ingress. The Node API routes authenticate the verified owner and send requests server-to-server to the worker.

Do not expose the standalone local FastAPI web app to the public internet. Its no-auth `/api/voice/*` convenience endpoints are designed for localhost only; always bind it to `127.0.0.1`. Use a separate secured listener/gateway that exposes **only** bearer-protected `/v1/*` endpoints for remote deployments, with quotas, TLS, request size limits and CSRF protection. Do not publicly forward `/api/voice/*` through a tunnel.

### API overview

| Route | Purpose | Security |
|---|---|---|
| `GET /api/voice/status` | Config, worker and sample status | No secrets |
| `POST /api/voice/sample` | Upload approved sample | Owner Google session (Vercel) or localhost-only |
| `DELETE /api/voice/sample` | Delete uploaded sample | Owner or localhost-only |
| `POST /api/voice/speak` | Generate sample voice TTS from text | Owner or localhost-only |
| `POST /api/voice/chat` | Text → Ollama → Chatterbox | Owner or localhost-only |
| `POST /api/voice/turn` | Recorded speech → Whisper → Ollama → Chatterbox | Owner or localhost-only |

The remote `/v1/*` routes require `MINI_WORKER_TOKEN`. The browser never sees this token or an ElevenLabs API key. The local recording is not uploaded to Vercel unless the user explicitly presses upload/voice send through a configured remote worker.

## Required production improvements

- Voice sample editing, multiple references per user and voice-profile isolation; worker currently holds **one** reference for a **single-owner prototype**.
- Streaming STT, incremental LLM tokens, streaming TTS chunks and true interruption for lower latency.
- Rate limits, model queue, warm startup, token budgets, audio retention limits and encryption at rest.
- Real device testing for microphone/capture and language switching. Hindi detection uses language auto-detection from Whisper; typed Devanagari uses the Hindi TTS path.
- Voice owner rights confirmation and delete controls are present, but multi-user consent, data policies and export are later work.
