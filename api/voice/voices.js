import { requireOwner, noStore } from '../_shared/auth.js';

export default async function handler(req, res) {
  noStore(res);
  if (req.method !== 'GET') { res.setHeader('Allow', 'GET'); return res.status(405).json({ error: 'Method not allowed' }); }
  if (!requireOwner(req, res)) return;
  const key = process.env.ELEVENLABS_API_KEY;
  if (!key) return res.status(503).json({ error: 'ElevenLabs is not configured.' });
  try {
    const upstream = await fetch('https://api.elevenlabs.io/v2/voices?page_size=100', { headers: { 'xi-api-key': key }, signal: AbortSignal.timeout(12000) });
    if (!upstream.ok) return res.status(502).json({ error: 'Could not fetch voices from the ElevenLabs account.' });
    const data = await upstream.json();
    const voices = Array.isArray(data.voices) ? data.voices.map((voice) => ({
      voiceId: String(voice.voice_id || '').slice(0, 80),
      name: String(voice.name || 'Untitled').slice(0, 100),
      category: String(voice.category || '').slice(0, 40)
    })).filter((voice) => /^[a-zA-Z0-9]{12,80}$/.test(voice.voiceId)) : [];
    return res.status(200).json({ voices, hasMore: Boolean(data.has_more), defaultVoiceId: process.env.ELEVENLABS_VOICE_ID || '21m00Tcm4TlvDq8ikWAM' });
  } catch {
    return res.status(502).json({ error: 'ElevenLabs voices request failed.' });
  }
}
