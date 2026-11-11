import { noStore, ownerEmail, sameOrigin } from '../_shared/auth.js';
import { callWorker } from '../_shared/worker.js';

/** Super admins: MINI_ADMIN_EMAILS (comma separated), else the owner email. */
export function adminEmails() {
  const raw = process.env.MINI_ADMIN_EMAILS || ownerEmail();
  return raw.split(',').map((e) => e.trim().toLowerCase()).filter(Boolean);
}

async function supabaseUser(token, { fetchImpl = fetch } = {}) {
  const url = process.env.MINI_SUPABASE_URL || '';
  const key = process.env.MINI_SUPABASE_PUBLISHABLE_KEY || '';
  if (!/^https:\/\/[a-z0-9-]+\.supabase\.co$/.test(url) || !/^sb_publishable_/.test(key)) return { status: 503 };
  try {
    const r = await fetchImpl(url + '/auth/v1/user', {
      headers: { apikey: key, Authorization: 'Bearer ' + token }, signal: AbortSignal.timeout(5000)
    });
    if (!r.ok) return { status: 401 };
    const user = await r.json();
    return user?.id ? { user } : { status: 401 };
  } catch { return { status: 503 }; }
}

/**
 * Super admin infra switch: local server vs API models (global + per user).
 * The admin's Supabase session is checked here; the worker is reached
 * server-to-server with the worker token. API keys never pass through here.
 */
export default async function handler(req, res, { fetchImpl = fetch, worker = callWorker } = {}) {
  noStore(res);
  if (!['GET', 'POST'].includes(req.method)) {
    res.setHeader('Allow', 'GET, POST');
    return res.status(405).json({ error: 'Method not allowed' });
  }
  if (req.method === 'POST' && !sameOrigin(req)) return res.status(403).json({ error: 'Cross-site request refused.' });
  const token = /^Bearer (.{20,6000})$/.exec(String(req.headers?.authorization || ''))?.[1];
  if (!token) return res.status(401).json({ error: 'Sign in first.' });
  const { user, status } = await supabaseUser(token, { fetchImpl });
  if (!user) return res.status(status).json({ error: status === 401 ? 'Sign in again.' : 'Identity check unavailable.' });
  const email = String(user.email || '').toLowerCase();
  if (!user.email_confirmed_at || !adminEmails().includes(email)) return res.status(403).json({ error: 'Admins only.' });
  try {
    if (req.method === 'GET') return res.status(200).json(await worker('admin/infra', { method: 'GET', timeoutMs: 6000 }));
    const body = req.body && typeof req.body === 'object' ? req.body : {};
    const action = body.action || 'settings';
    if (action === 'settings') {
      if (!body.settings || typeof body.settings !== 'object') return res.status(422).json({ error: 'settings required' });
      return res.status(200).json(await worker('admin/infra', { method: 'POST', body: { settings: body.settings, by: email }, timeoutMs: 6000 }));
    }
    if (action === 'set_key' || action === 'remove_key') {
      // The key passes straight to the private worker over HTTPS; it is never logged or returned.
      if (typeof body.name !== 'string' || (action === 'set_key' && typeof body.value !== 'string'))
        return res.status(422).json({ error: 'name and value required' });
      return res.status(200).json(await worker('admin/keys', { method: 'POST', timeoutMs: 6000,
        body: { action: action === 'set_key' ? 'set' : 'remove', name: body.name,
          ...(action === 'set_key' ? { value: body.value } : {}), by: email } }));
    }
    if (action === 'models') {
      if (typeof body.provider !== 'string') return res.status(422).json({ error: 'provider required' });
      const slot = typeof body.slot === 'string' ? body.slot : undefined;
      return res.status(200).json(await worker('admin/models', { method: 'POST', body: { provider: body.provider, ...(slot ? { slot } : {}) }, timeoutMs: 15000 }));
    }
    return res.status(422).json({ error: 'unknown action' });
  } catch (error) {
    return res.status(error.statusCode && error.statusCode < 600 ? error.statusCode : 502).json({ error: error.message });
  }
}
