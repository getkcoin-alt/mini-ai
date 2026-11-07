import { requireOwner, sameOrigin, noStore } from '../_shared/auth.js';

export default async function handler(req, res) {
  noStore(res);
  if (req.method !== 'POST') { res.setHeader('Allow', 'POST'); return res.status(405).json({ error: 'Method not allowed' }); }
  if (!sameOrigin(req)) return res.status(403).json({ error: 'Request origin denied' });
  if (!requireOwner(req, res)) return;
  const key = process.env.ELEVENLABS_API_KEY;
  if (!key) return res.status(503).json({ error: 'ElevenLabs voice is not configured.' });
  const body = req.body || {};
  const speechText = body.text;
  const requestedVoice = body.voiceId;
  if (typeof speechText !== 'string' || speechText.trim().length === 0 || speechText.length > 700)
    return res.status(400).json({ error: 'Speech text must be 1-700 characters.' });
  if (requestedVoice !== undefined && (typeof requestedVoice !== 'string' || !/^[a-zA-Z0-9]{12,80}$/.test(requestedVoice)))
    return res.status(400).json({ error: 'Invalid voice ID.' });
  const voiceId = requestedVoice || process.env.ELEVENLABS_VOICE_ID || '21m00Tcm4TlvDq8ikWAM';
  const modelId = process.env.ELEVENLABS_MODEL_ID || 'eleven_flash_v2_5';
  const upstreamUrl = new URL('https://api.elevenlabs.io/v1/text-to-speech/' + encodeURIComponent(voiceId) + '/stream');
  upstreamUrl.searchParams.set('output_format', 'mp3_44100_128');
  try {
    const upstream = await fetch(upstreamUrl, {
      method: 'POST', headers: { 'xi-api-key': key, 'Content-Type': 'application/json', Accept: 'audio/mpeg' },
      body: JSON.stringify({
        text: speechText.trim(), model_id: modelId,
        // Preserves the previous itsmay Mini voice settings.
        voice_settings: { stability: 0.28, similarity_boost: 0.82, style: 0.60, use_speaker_boost: true }
      }),
      signal: AbortSignal.timeout(45000)
    });
    if (!upstream.ok || !upstream.body) return res.status(502).json({ error: 'ElevenLabs TTS request was rejected. Check voice, key, credits and API permissions.' });
    res.status(200);
    res.setHeader('Content-Type', 'audio/mpeg');
    res.setHeader('Cache-Control', 'no-store');
    const reader = upstream.body.getReader();
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        if (!res.writableEnded) res.write(Buffer.from(value));
        else break;
      }
      res.end();
    } finally { reader.releaseLock(); }
  } catch {
    if (!res.headersSent) return res.status(502).json({ error: 'ElevenLabs voice service could not be reached.' });
    res.end();
  }
}
