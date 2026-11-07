import { OAuth2Client } from 'google-auth-library';
import { makeSession, setSessionCookie, noStore, ownerEmail, sameOrigin, sessionConfigured } from '../_shared/auth.js';

export default async function handler(req, res) {
  noStore(res);
  if (req.method !== 'POST') { res.setHeader('Allow', 'POST'); return res.status(405).json({ error: 'Method not allowed' }); }
  if (!sameOrigin(req)) return res.status(403).json({ error: 'Request origin denied' });
  const clientId = process.env.GOOGLE_CLIENT_ID;
  if (!clientId || !sessionConfigured()) return res.status(503).json({ error: 'Google login is not configured yet.' });
  const token = req.body?.credential;
  if (typeof token !== 'string' || token.length < 100 || token.length > 10000) return res.status(400).json({ error: 'Invalid credential' });
  try {
    const client = new OAuth2Client(clientId);
    const ticket = await client.verifyIdToken({ idToken: token, audience: clientId });
    const payload = ticket.getPayload();
    const email = String(payload?.email || '').toLowerCase();
    if (!payload?.sub || payload?.email_verified !== true || email !== ownerEmail())
      return res.status(403).json({ error: 'This voice preview is restricted to the configured Google account.' });
    // When using Google Workspace, its hd claim is an additional assurance of domain ownership.
    // Owner email is compared against the *verified* Google ID token, never against browser input.
    const session = makeSession({ sub: payload.sub, email });
    setSessionCookie(res, session);
    return res.status(200).json({ authenticated: true, email });
  } catch {
    return res.status(401).json({ error: 'Google sign-in could not be verified.' });
  }
}
