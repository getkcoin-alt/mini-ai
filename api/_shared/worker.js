import { noStore, requireOwner, sameOrigin } from './auth.js';

function config() {
  const token = process.env.MINI_WORKER_TOKEN || '';
  const raw = process.env.MINI_WORKER_URL || '';
  if (token.length < 32 || !raw) return null;
  try {
    const url = new URL(raw);
    const local = ['localhost', '127.0.0.1'].includes(url.hostname);
    const production = process.env.NODE_ENV === 'production';
    if (url.username || url.password || url.search || url.hash || url.pathname !== '/' ||
      !((url.protocol === 'https:') || (!production && url.protocol === 'http:' && local))) return null;
    return { url, token };
  } catch { return null; }
}

export function workerConfigured() { return Boolean(config()); }

export async function callWorker(path, { method = 'POST', body, timeoutMs = 55000 } = {}) {
  const connection = config();
  if (!connection) {
    const error = new Error('Self-hosted Mini voice worker is not configured.');
    error.statusCode = 503;
    throw error;
  }
  const target = new URL('/v1/' + path, connection.url);
  try {
    const upstream = await fetch(target, {
      method,
      headers: { 'x-mini-worker-token': connection.token, 'Content-Type': 'application/json' },
      ...(body !== undefined && method !== 'GET' && method !== 'DELETE' ? { body: JSON.stringify(body) } : {}),
      signal: AbortSignal.timeout(timeoutMs),
      cache: 'no-store',
    });
    const payload = await upstream.json().catch(() => ({}));
    if (!upstream.ok) {
      const error = new Error(
        upstream.status === 401 ? 'Voice worker refused authentication. Check the worker token.' :
        typeof payload.detail === 'string' ? payload.detail.slice(0, 180) : 'Local voice worker failed.'
      );
      error.statusCode = upstream.status;
      throw error;
    }
    return payload;
  } catch (cause) {
    if (cause.statusCode) throw cause;
    const error = new Error('Private voice worker is unreachable. Run it locally or configure a secure HTTPS endpoint.');
    error.statusCode = 502;
    throw error;
  }
}

export function validateVoiceRequest(req, res, allowed) {
  noStore(res);
  if (!allowed.includes(req.method)) {
    res.setHeader('Allow', allowed.join(', '));
    res.status(405).json({ error: 'Method not allowed' });
    return false;
  }
  if (req.method !== 'GET' && !sameOrigin(req)) {
    res.status(403).json({ error: 'Cross-origin voice request denied.' });
    return false;
  }
  if (!requireOwner(req, res)) return false;
  return true;
}

export function respondVoiceError(res, error) {
  // Never echo a worker URL, token, private trace, model-generated stack trace or raw audio.
  const code = Number.isInteger(error.statusCode) && error.statusCode >= 400 && error.statusCode < 600
    ? error.statusCode : 502;
  return res.status(code).json({ error: String(error.message || 'Voice worker unavailable').slice(0, 200) });
}
