# Mini AI Voice — ElevenLabs setup

Updated: 2026-11-07. Frontend + protected server routes are implemented; provider credentials are not present yet.

## Previous itsmay behavior

- `core/voice/tts_elevenlabs.py` streams ElevenLabs TTS using Flash v2.5, stability 0.28, similarity 0.82, style 0.60 and speaker boost.
- `core/config.py` defaults voice ID to `21m00Tcm4TlvDq8ikWAM` (Rachel). This is a code default, not a confirmed voice selected in the account.

## Connect the account, once

1. Open https://elevenlabs.io/app and sign in with **Continue with Google** using the intended account. This is a human authorization action, not something the Mini frontend can do automatically.
2. Create a restricted **ElevenLabs API key** from your ElevenLabs account. Set it **only** in Vercel project environment variables. Google sign-in to ElevenLabs does not replace an API key.
3. Find the voice you used previously in the ElevenLabs Voices dashboard. Copy its voice ID. For real continuous two-way conversation, create a private ElevenLabs Agent with signed URL authorization and copy its Agent ID.
4. Create a Google **Web OAuth client ID** for Mini AI in Google Cloud Console. Authorized JavaScript origins should include your actual live Mini AI origin (for example `https://mini-ai-gitkcoin.vercel.app`).
5. Configure in Vercel > mini-ai > Settings > Environment Variables:

| Name | Meaning |
| --- | --- |
| `GOOGLE_CLIENT_ID` | Public Google web client ID |
| `MINI_OWNER_EMAIL` | Authorized account email |
| `MINI_SESSION_SECRET` | Random 32+ character server secret |
| `ELEVENLABS_API_KEY` | Server-only ElevenLabs account key |
| `ELEVENLABS_VOICE_ID` | Selected ElevenLabs voice ID |
| `ELEVENLABS_MODEL_ID` | `eleven_flash_v2_5` |
| `ELEVENLABS_AGENT_ID` | Optional private Agent ID for true full-duplex calls |

6. Redeploy after saving environment variables. Click Google sign-in within Mini AI and open **Preferences**. Once logged in, the app can list account voices and test the selected one.

Never commit or paste provider secrets into the frontend or chat.

## Runtime and trust boundaries

- `GET /api/voice/status` reveals only readiness flags and whether an owner session exists.
- `POST /api/auth/google` verifies Google's signed ID token (audience, email, expiry and signature), then sets a signed 12-hour HttpOnly cookie.
- `GET /api/voice/voices` accesses the account's voice list after owner authentication.
- `POST /api/voice/speak` streams ElevenLabs TTS via server-held credentials (spoken output uses Mini's scripted replies until a real reasoning backend is attached).
- `POST /api/voice/signed-url` creates an authenticated, expiring connection for a private ElevenLabs Agent. The client SDK then manages real two-way voice.
- The agent's **own configured instructions and memory** control live calls; frontend Friend/Mentor mode sends a contextual preference update only. Persistent personal memory is not synchronized yet.

Owner-only is deliberate to prevent a public demo from consuming paid voice credits. Later multi-user releases need account isolation, quotas, explicit consent, metering and rate limiting.

References: https://elevenlabs.io/docs/eleven-agents/customization/authentication , https://elevenlabs.io/docs/eleven-agents/libraries/java-script , https://developers.google.com/identity/gsi/web/guides/verify-google-id-token .
