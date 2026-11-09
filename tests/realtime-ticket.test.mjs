import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import handler, { issueRealtimeTicket } from '../api/voice/realtime-config.js';
import { miniLiveWsUrl } from '../mini-realtime-protocol.js';

const KEYS = ['MINI_REALTIME_AUDIENCE', 'MINI_REQUIRE_AGE_CONFIRMATION', 'MINI_WORKER_TOKEN', 'MINI_OWNER_EMAIL', 'MINI_SUPABASE_URL', 'MINI_SUPABASE_PUBLISHABLE_KEY',
  'MINI_REALTIME_ENABLED', 'MINI_REALTIME_GATEWAY_READY', 'MINI_REALTIME_WS_URL'];
const saved = Object.fromEntries(KEYS.map((k) => [k, process.env[k]]));
const realFetch = globalThis.fetch;
test.after(() => { globalThis.fetch = realFetch; for (const k of KEYS) { if (saved[k] === undefined) delete process.env[k]; else process.env[k] = saved[k]; } });

function env(on = true) {
  Object.assign(process.env, { MINI_WORKER_TOKEN: 'w'.repeat(48), MINI_OWNER_EMAIL: 'owner@example.com',
    MINI_SUPABASE_URL: 'https://abcdefgh.supabase.co', MINI_SUPABASE_PUBLISHABLE_KEY: 'sb_publishable_x',
    MINI_REALTIME_ENABLED: String(on), MINI_REALTIME_GATEWAY_READY: String(on),
    MINI_REALTIME_WS_URL: 'wss://api.example.com/v1/realtime/browser' });
}
function supaUser(user) { globalThis.fetch = async () => new Response(JSON.stringify(user), { status: user ? 200 : 401 }); }
async function call() {
  const res = { code: 0, body: null, setHeader() {}, status(c) { this.code = c; return this; }, json(b) { this.body = b; return this; } };
  await handler({ method: 'GET', headers: { authorization: 'Bearer ' + 'x'.repeat(40) } }, res);
  return res;
}

test('owner gets a signed single-use ticket and the live URL', async () => {
  env(); supaUser({ id: 'u1', email: 'Owner@Example.com', email_confirmed_at: '2026-11-09' });
  const res = await call();
  assert.equal(res.code, 200);
  assert.equal(res.body.enabled, true);
  assert.equal(res.body.wsUrl, 'wss://api.example.com/v1/realtime/browser');
  const [payload, sig] = res.body.ticket.split('.');
  assert.equal(sig, createHmac('sha256', 'w'.repeat(48)).update('mini.realtime.ticket.v1.' + payload).digest('base64url'));
  const body = JSON.parse(Buffer.from(payload, 'base64url'));
  assert.equal(body.sub, 'u1');
  assert.ok(body.exp - Date.now() / 1000 <= 60);
  assert.doesNotMatch(JSON.stringify(res.body), /w{48}/);
});

test('no ticket for other accounts, flags off, or bad sessions', async () => {
  env(); supaUser({ id: 'u2', email: 'someone@example.com', email_confirmed_at: '2026-11-09' });
  let res = await call(); assert.equal(res.body.enabled, false); assert.equal(res.body.reason, 'owner_only'); assert.equal(res.body.ticket, undefined);
  env(false); supaUser({ id: 'u1', email: 'owner@example.com', email_confirmed_at: '2026-11-09' });
  res = await call(); assert.equal(res.body.enabled, false); assert.equal(res.body.ticket, undefined);
  env(); supaUser(null);
  res = await call(); assert.equal(res.code, 401);
  assert.throws(() => issueRealtimeTicket('u1', { secret: 'short' }));
});

test('live URL must be a plain wss worker browser path', () => {
  assert.equal(miniLiveWsUrl('wss://api.example.com/v1/realtime/browser'), 'wss://api.example.com/v1/realtime/browser');
  for (const bad of ['ws://api.example.com/v1/realtime/browser', 'wss://api.example.com/v1/realtime',
    'wss://api.example.com/v1/realtime/browser?token=x', 'wss://u:p@api.example.com/v1/realtime/browser', '', null, 'javascript:alert(1)'])
    assert.equal(miniLiveWsUrl(bad), '', String(bad));
});

test('audience=all lets any confirmed account in; unconfirmed email never', async () => {
  env(); process.env.MINI_REALTIME_AUDIENCE = 'all'; delete process.env.MINI_REQUIRE_AGE_CONFIRMATION;
  supaUser({ id: 'u9', email: 'friend@example.com', email_confirmed_at: '2026-11-10' });
  let res = await call(); assert.equal(res.body.enabled, true); assert.ok(res.body.ticket);
  supaUser({ id: 'u9', email: 'friend@example.com', email_confirmed_at: null });
  res = await call(); assert.equal(res.body.enabled, false); assert.equal(res.body.reason, 'email_unconfirmed');
  delete process.env.MINI_REALTIME_AUDIENCE;
});

test('18+ gate reads the user profile when required', async () => {
  env(); process.env.MINI_REALTIME_AUDIENCE = 'all'; process.env.MINI_REQUIRE_AGE_CONFIRMATION = 'true';
  const user = { id: 'u7', email: 'a@example.com', email_confirmed_at: '2026-11-10' };
  for (const [rows, enabled] of [[[{ age_confirmed_at: '2026-11-10' }], true], [[{ age_confirmed_at: null }], false], [[], false]]) {
    globalThis.fetch = async (url) => new Response(JSON.stringify(String(url).includes('/rest/v1/') ? rows : user), { status: 200 });
    const res = await call();
    assert.equal(res.body.enabled, enabled, JSON.stringify(rows));
    if (!enabled) assert.equal(res.body.reason, 'age_confirmation_required');
  }
  delete process.env.MINI_REALTIME_AUDIENCE; delete process.env.MINI_REQUIRE_AGE_CONFIRMATION;
});
