import { createHmac, randomBytes } from 'node:crypto';
import { MINI_REALTIME_PROTOCOL, MINI_WS_PATH } from '../../mini-realtime-protocol.js';
import { ownerEmail } from '../_shared/auth.js';

const TICKET_CONTEXT = 'mini.realtime.ticket.v1.';
const TICKET_TTL_SECONDS = 60;

function noStore(res) {
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('X-Content-Type-Options', 'nosniff');
}

/** Short-lived, single-use pass the worker verifies with the shared worker token. */
export function issueRealtimeTicket(sub, { secret = process.env.MINI_WORKER_TOKEN || '', now = Date.now() } = {}) {
  if (secret.length < 32 || !sub) throw new Error('Realtime ticket not configured');
  const payload = Buffer.from(JSON.stringify({
    sub, exp: Math.floor(now / 1000) + TICKET_TTL_SECONDS, nonce: randomBytes(18).toString('base64url')
  })).toString('base64url');
  const sig = createHmac('sha256', secret).update(TICKET_CONTEXT + payload).digest('base64url');
  return payload + '.' + sig;
}

/** 18+ confirmation saved on the user's own profile (read with their token, RLS). */
async function ageConfirmed(url, key, token, userId) {
  try {
    const r = await fetch(url + '/rest/v1/mini_profiles?select=age_confirmed_at&user_id=eq.' + encodeURIComponent(userId), {
      headers: { apikey: key, Authorization: 'Bearer ' + token }, signal: AbortSignal.timeout(5000)
    });
    if (!r.ok) return false;
    const rows = await r.json();
    return Boolean(rows?.[0]?.age_confirmed_at);
  } catch { return false; }
}

function liveWsUrl() {
  const url = process.env.MINI_REALTIME_WS_URL || '';
  return /^wss:\/\/[a-z0-9.-]+(:\d+)?\/v1\/realtime\/browser$/.test(url) ? url : '';
}

/**
 * Readiness + ticket for live voice. Vercel functions cannot hold WebSockets,
 * so the signed-in user's browser connects directly to the private worker
 * (MINI_REALTIME_WS_URL) with a 60-second, single-use ticket. The worker also
 * re-verifies the Supabase session and requires both to name the same user.
 * Fail-closed unless MINI_REALTIME_ENABLED and MINI_REALTIME_GATEWAY_READY are true.
 */
export default async function handler(req, res) {
  noStore(res);
  if (req.method !== 'GET') {
    res.setHeader('Allow', 'GET');
    return res.status(405).json({ enabled: false });
  }
  const token = /^Bearer (.{20,6000})$/.exec(String(req.headers?.authorization || ''))?.[1];
  if (!token) return res.status(401).json({ enabled: false, error: 'Sign in to Mini first.' });
  const url = process.env.MINI_SUPABASE_URL || '';
  const key = process.env.MINI_SUPABASE_PUBLISHABLE_KEY || '';
  if (!/^https:\/\/[a-z0-9-]+\.supabase\.co$/.test(url) || !/^sb_publishable_/.test(key))
    return res.status(503).json({ enabled: false, reason: 'auth_unconfigured' });
  let user;
  try {
    const response = await fetch(url + '/auth/v1/user', {
      headers: { apikey: key, Authorization: 'Bearer ' + token }, signal: AbortSignal.timeout(5000)
    });
    if (!response.ok) return res.status(401).json({ enabled: false, error: 'Sign in to Mini again.' });
    user = await response.json();
    if (!user?.id) return res.status(401).json({ enabled: false, error: 'Sign in to Mini again.' });
  } catch {
    return res.status(503).json({ enabled: false, reason: 'identity_unavailable' });
  }
  const base = { protocol: MINI_REALTIME_PROTOCOL, wsPath: MINI_WS_PATH,
    input: { format: 'pcm16', sampleRate: 16000, frameMs: 20 }, output: { format: 'pcm16', sampleRate: 24000 } };
  const flagsOn = process.env.MINI_REALTIME_ENABLED === 'true' && process.env.MINI_REALTIME_GATEWAY_READY === 'true';
  const wsUrl = liveWsUrl();
  if (!flagsOn || !wsUrl || (process.env.MINI_WORKER_TOKEN || '').length < 32)
    return res.status(200).json({ enabled: false, ...base, reason: 'nfc_gateway_not_ready' });
  // Who may talk live: MINI_REALTIME_AUDIENCE=owner (default) or all. Either
  // way the account's email must be confirmed.
  if (!user.email_confirmed_at) return res.status(200).json({ enabled: false, ...base, reason: 'email_unconfirmed' });
  const everyone = process.env.MINI_REALTIME_AUDIENCE === 'all';
  if (!everyone && String(user.email || '').toLowerCase() !== ownerEmail())
    return res.status(200).json({ enabled: false, ...base, reason: 'owner_only' });
  if (process.env.MINI_REQUIRE_AGE_CONFIRMATION === 'true' && !(await ageConfirmed(url, key, token, user.id)))
    return res.status(200).json({ enabled: false, ...base, reason: 'age_confirmation_required' });
  return res.status(200).json({ enabled: true, ...base, wsUrl, ticket: issueRealtimeTicket(user.id) });
}
