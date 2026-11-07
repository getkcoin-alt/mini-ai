import { requireOwner, noStore, sameOrigin } from '../_shared/auth.js';

export default async function handler(req, res) {
  noStore(res);
  if (req.method !== 'POST') { res.setHeader('Allow', 'POST'); return res.status(405).json({ error: 'Method not allowed' }); }
  if (!sameOrigin(req)) return res.status(403).json({ error: 'Request origin denied' });
  if (!requireOwner(req, res)) return;
  const key = process.env.ELEVENLABS_API_KEY;
  const agentId = process.env.ELEVENLABS_AGENT_ID;
  if (!key || !agentId) return res.status(503).json({ error: 'ElevenLabs Agent is not yet configured.' });
  if (!/^[a-zA-Z0-9_-]{10,100}$/.test(agentId)) return res.status(500).json({ error: 'Invalid server agent configuration.' });
  try {
    const url = new URL('https://api.elevenlabs.io/v1/convai/conversation/get-signed-url');
    url.searchParams.set('agent_id', agentId);
    const upstream = await fetch(url, { headers: { 'xi-api-key': key }, signal: AbortSignal.timeout(12000) });
    if (!upstream.ok) return res.status(502).json({ error: 'ElevenLabs could not open a signed voice session.' });
    const response = await upstream.json();
    const signedUrl = String(response.signed_url || '');
    const parsed = new URL(signedUrl);
    if (parsed.protocol !== 'wss:' || parsed.hostname !== 'api.elevenlabs.io') throw new Error('Unexpected signed URL origin');
    return res.status(200).json({ signedUrl });
  } catch {
    return res.status(502).json({ error: 'Could not start the ElevenLabs voice session.' });
  }
}
