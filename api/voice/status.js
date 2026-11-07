import { readSession, sessionConfigured, noStore } from '../_shared/auth.js';

export default function handler(req, res) {
  noStore(res);
  if (req.method !== 'GET') { res.setHeader('Allow', 'GET'); return res.status(405).json({ error: 'Method not allowed' }); }
  const owner = readSession(req);
  return res.status(200).json({
    authReady: Boolean(process.env.GOOGLE_CLIENT_ID && sessionConfigured()),
    googleClientId: process.env.GOOGLE_CLIENT_ID || '',
    ownerSignedIn: Boolean(owner),
    ownerEmail: owner ? owner.email : '',
    ttsReady: Boolean(process.env.ELEVENLABS_API_KEY && (process.env.ELEVENLABS_VOICE_ID || '21m00Tcm4TlvDq8ikWAM')),
    agentReady: Boolean(process.env.ELEVENLABS_API_KEY && process.env.ELEVENLABS_AGENT_ID),
    mode: 'owner-only-preview',
    // Never return ElevenLabs API keys, session secrets, or signed connection URLs here.
  });
}
