import { clearSessionCookie, noStore, sameOrigin } from '../_shared/auth.js';

export default function handler(req, res) {
  noStore(res);
  if (req.method !== 'POST') { res.setHeader('Allow', 'POST'); return res.status(405).json({ error: 'Method not allowed' }); }
  if (!sameOrigin(req)) return res.status(403).json({ error: 'Request origin denied' });
  clearSessionCookie(res);
  return res.status(200).json({ authenticated: false });
}
