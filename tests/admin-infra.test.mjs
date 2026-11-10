import test from 'node:test';
import assert from 'node:assert/strict';
import handler, { adminEmails } from '../api/admin/infra.js';

function res() {
  return { statusCode: 0, body: null, headers: {}, setHeader(k, v) { this.headers[k] = v; },
    status(c) { this.statusCode = c; return this; }, json(b) { this.body = b; return this; } };
}
const env = { MINI_SUPABASE_URL: 'https://abc.supabase.co', MINI_SUPABASE_PUBLISHABLE_KEY: 'sb_publishable_x',
  MINI_ADMIN_EMAILS: 'boss@example.com' };
const auth = { authorization: 'Bearer ' + 'x'.repeat(40), host: 'mini.example', origin: 'https://mini.example' };
const userFetch = (user) => async () => ({ ok: true, json: async () => user });

test('admin list falls back to owner email', () => {
  const saved = process.env.MINI_ADMIN_EMAILS; delete process.env.MINI_ADMIN_EMAILS;
  process.env.MINI_OWNER_EMAIL = 'Owner@Example.com';
  assert.deepEqual(adminEmails(), ['owner@example.com']);
  delete process.env.MINI_OWNER_EMAIL; if (saved) process.env.MINI_ADMIN_EMAILS = saved;
});

test('non-admins and unconfirmed admins are refused; worker never called', async () => {
  Object.assign(process.env, env);
  let called = false;
  const worker = async () => { called = true; return {}; };
  for (const user of [{ id: '1', email: 'someone@example.com', email_confirmed_at: 'x' },
                      { id: '2', email: 'boss@example.com' }]) {
    const r = res();
    await handler({ method: 'GET', headers: auth }, r, { fetchImpl: userFetch(user), worker });
    assert.equal(r.statusCode, 403);
  }
  const r = res();
  await handler({ method: 'GET', headers: {} }, r, { fetchImpl: userFetch({}), worker });
  assert.equal(r.statusCode, 401);
  assert.equal(called, false);
});

test('admin can read and save; cross-site POST refused', async () => {
  Object.assign(process.env, env);
  const boss = { id: '3', email: 'Boss@Example.com', email_confirmed_at: 'x' };
  const calls = [];
  const worker = async (path, opts) => { calls.push([path, opts.method, opts.body]); return { ok: true }; };
  let r = res();
  await handler({ method: 'GET', headers: auth }, r, { fetchImpl: userFetch(boss), worker });
  assert.equal(r.statusCode, 200);
  r = res();
  const settings = { default: { mode: 'api', llm_provider: 'groq', llm_model: '' }, users: {} };
  await handler({ method: 'POST', headers: auth, body: { settings } }, r, { fetchImpl: userFetch(boss), worker });
  assert.equal(r.statusCode, 200);
  assert.deepEqual(calls[1], ['admin/infra', 'POST', { settings, by: 'boss@example.com' }]);
  r = res();
  await handler({ method: 'POST', headers: { ...auth, origin: 'https://evil.example' }, body: { settings } }, r,
    { fetchImpl: userFetch(boss), worker });
  assert.equal(r.statusCode, 403);
});
