import { createHmac, timingSafeEqual } from 'node:crypto';

export const COOKIE_NAME = '__Host-mini_session';
const MAX_AGE_SECONDS = 60 * 60 * 12;

function signingSecret() {
  const value = process.env.MINI_SESSION_SECRET || '';
  return value.length >= 32 ? value : '';
}

function sign(data, secret) {
  return createHmac('sha256', secret).update(data).digest('base64url');
}

export function sessionConfigured() {
  return Boolean(signingSecret());
}

export function makeSession({ sub, email, now = Date.now() }) {
  const secret = signingSecret();
  if (!secret || !sub || !email) throw new Error('Session not configured');
  const payload = Buffer.from(JSON.stringify({ sub, email: email.toLowerCase(), exp: Math.floor(now / 1000) + MAX_AGE_SECONDS })).toString('base64url');
  return payload + '.' + sign(payload, secret);
}

export function verifySession(token, now = Date.now()) {
  const secret = signingSecret();
  if (!secret || typeof token !== 'string' || token.length > 2048) return null;
  const parts = token.split('.');
  if (parts.length !== 2 || !parts[0] || !parts[1]) return null;
  try {
    const expected = Buffer.from(sign(parts[0], secret), 'base64url');
    const supplied = Buffer.from(parts[1], 'base64url');
    if (expected.length !== supplied.length || !timingSafeEqual(expected, supplied)) return null;
    const payload = JSON.parse(Buffer.from(parts[0], 'base64url').toString('utf8'));
    if (!payload.sub || !payload.email || !Number.isInteger(payload.exp) || payload.exp <= Math.floor(now / 1000)) return null;
    if (payload.email.toLowerCase() !== ownerEmail()) return null;
    return { sub: payload.sub, email: payload.email, exp: payload.exp };
  } catch { return null; }
}

export function ownerEmail() {
  return (process.env.MINI_OWNER_EMAIL || 'karnveer@scriza.in').trim().toLowerCase();
}

export function sameOrigin(req) {
  const origin = req.headers?.origin;
  const host = req.headers?.host;
  if (typeof origin !== 'string' || !host) return false;
  try {
    const parsed = new URL(origin);
    return parsed.protocol === 'https:' && parsed.host === host
      || process.env.NODE_ENV !== 'production' && parsed.protocol === 'http:' && parsed.host === host;
  } catch { return false; }
}

export function readSession(req) {
  const cookies = String(req.headers?.cookie || '').split(';');
  const match = cookies.find((item) => item.trim().startsWith(COOKIE_NAME + '='));
  if (!match) return null;
  return verifySession(match.trim().slice(COOKIE_NAME.length + 1));
}

export function requireOwner(req, res) {
  const session = readSession(req);
  if (!session) {
    res.status(401).json({ error: 'Sign in with the configured Google account to use ElevenLabs.' });
    return null;
  }
  return session;
}

export function setSessionCookie(res, token) {
  res.setHeader('Set-Cookie', COOKIE_NAME + '=' + token + '; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=' + MAX_AGE_SECONDS);
}
export function clearSessionCookie(res) {
  res.setHeader('Set-Cookie', COOKIE_NAME + '=; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=0');
}
export function noStore(res) {
  res.setHeader('Cache-Control', 'no-store, no-cache, must-revalidate');
  res.setHeader('X-Content-Type-Options', 'nosniff');
}
