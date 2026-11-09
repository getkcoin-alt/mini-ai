import test from 'node:test';
import assert from 'node:assert/strict';
import handler from '../api/auth/supabase-owner.js';
import { verifySession, COOKIE_NAME } from '../api/_shared/auth.js';

const saved = { ...process.env };
test.after(() => { for (const k of ['MINI_SESSION_SECRET', 'MINI_OWNER_EMAIL', 'MINI_SUPABASE_URL', 'MINI_SUPABASE_PUBLISHABLE_KEY']) {
  if (saved[k] === undefined) delete process.env[k]; else process.env[k] = saved[k];
} });

function setup(user, status = 200) {
  process.env.MINI_SESSION_SECRET = 'b'.repeat(64);
  process.env.MINI_OWNER_EMAIL = 'owner@example.com';
  process.env.MINI_SUPABASE_URL = 'https://abcdefgh.supabase.co';
  process.env.MINI_SUPABASE_PUBLISHABLE_KEY = 'sb_publishable_test';
  globalThis.fetch = async (url) => {
    assert.match(String(url), /^https:\/\/abcdefgh\.supabase\.co\/auth\/v1\/user/);
    return new Response(JSON.stringify(status === 200 ? user : { msg: 'bad jwt' }), { status, headers: { 'Content-Type': 'application/json' } });
  };
}
function call(headers = {}) {
  const res = { code: 0, body: null, headers: {}, setHeader(k, v) { this.headers[k] = v; },
    status(c) { this.code = c; return this; }, json(b) { this.body = b; return this; } };
  const req = { method: 'POST', headers: { origin: 'https://mini.example', host: 'mini.example', authorization: 'Bearer ' + 'x'.repeat(40), ...headers } };
  return handler(req, res).then(() => res);
}

test('owner Mini account gets the private voice session', async () => {
  setup({ id: 'u1', email: 'Owner@Example.com', email_confirmed_at: '2026-11-09T00:00:00Z' });
  const res = await call();
  assert.equal(res.code, 200);
  const cookie = res.headers['Set-Cookie'];
  assert.match(cookie, new RegExp('^' + COOKIE_NAME + '='));
  const session = verifySession(cookie.split(';')[0].slice(COOKIE_NAME.length + 1));
  assert.equal(session.email, 'owner@example.com');
});

test('other accounts, unconfirmed emails and bad tokens are refused', async () => {
  setup({ id: 'u2', email: 'someone@example.com', email_confirmed_at: '2026-11-09T00:00:00Z' });
  assert.equal((await call()).code, 403);
  setup({ id: 'u3', email: 'owner@example.com', email_confirmed_at: null });
  assert.equal((await call()).code, 403);
  setup(null, 401);
  assert.equal((await call()).code, 401);
  setup({ id: 'u1', email: 'owner@example.com', email_confirmed_at: 'x' });
  assert.equal((await call({ authorization: '' })).code, 401);
  assert.equal((await call({ origin: 'https://evil.example' })).code, 403);
});
