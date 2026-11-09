import { makeSession, setSessionCookie, noStore, ownerEmail, sameOrigin, sessionConfigured } from '../_shared/auth.js';

/**
 * Turn a signed-in Mini (Supabase) account into the private voice owner
 * session, so the owner does not need a second Google sign-in.
 * The Supabase access token is verified remotely; only the configured owner
 * email with a confirmed address receives the voice cookie.
 */
export default async function handler(req, res) {
  noStore(res);
  if (req.method !== 'POST') { res.setHeader('Allow', 'POST'); return res.status(405).json({ error: 'Method not allowed' }); }
  if (!sameOrigin(req)) return res.status(403).json({ error: 'Request origin denied' });
  if (!sessionConfigured()) return res.status(503).json({ error: 'Private voice sign-in is not configured yet.' });
  const token = /^Bearer (.{20,6000})$/.exec(String(req.headers?.authorization || ''))?.[1];
  if (!token) return res.status(401).json({ error: 'Sign in to Mini first.' });
  const url = process.env.MINI_SUPABASE_URL || '';
  const key = process.env.MINI_SUPABASE_PUBLISHABLE_KEY || '';
  if (!/^https:\/\/[a-z0-9-]+\.supabase\.co$/.test(url) || !/^sb_publishable_/.test(key))
    return res.status(503).json({ error: 'Mini sign-in is not configured.' });
  let user;
  try {
    // Verify the access token with Supabase Auth itself (no service-role secret).
    const response = await fetch(url + '/auth/v1/user', {
      headers: { apikey: key, Authorization: 'Bearer ' + token },
      signal: AbortSignal.timeout(5000)
    });
    if (!response.ok) return res.status(401).json({ error: 'Sign in to Mini again.' });
    user = await response.json();
    if (!user?.id) return res.status(401).json({ error: 'Sign in to Mini again.' });
  } catch {
    return res.status(503).json({ error: 'Mini sign-in is unavailable right now.' });
  }
  const email = String(user.email || '').toLowerCase();
  if (!email || !user.email_confirmed_at || email !== ownerEmail())
    return res.status(403).json({ error: 'Private voice is restricted to the owner account.' });
  setSessionCookie(res, makeSession({ sub: 'supabase:' + user.id, email }));
  return res.status(200).json({ authenticated: true, email });
}
