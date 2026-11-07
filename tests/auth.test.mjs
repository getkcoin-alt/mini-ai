import test from 'node:test';
import assert from 'node:assert/strict';
import { makeSession, verifySession, readSession, sameOrigin, ownerEmail, sessionConfigured } from '../api/_shared/auth.js';

const prior = process.env.MINI_SESSION_SECRET;
const priorOwner = process.env.MINI_OWNER_EMAIL;
test.after(() => {
  if (prior === undefined) delete process.env.MINI_SESSION_SECRET; else process.env.MINI_SESSION_SECRET = prior;
  if (priorOwner === undefined) delete process.env.MINI_OWNER_EMAIL; else process.env.MINI_OWNER_EMAIL = priorOwner;
});

test('never accepts a session without a server secret', () => {
  delete process.env.MINI_SESSION_SECRET;
  assert.equal(sessionConfigured(), false);
  assert.equal(verifySession('eyJzdWIiOiJ1c2VyIn0.signature'), null);
  assert.throws(() => makeSession({ sub: 'uid', email: 'karnveer@scriza.in' }));
});

test('owner-only signed sessions reject modification, other owners and expiry', () => {
  process.env.MINI_SESSION_SECRET = 'testing-only-strong-random-secret-placeholder-32';
  process.env.MINI_OWNER_EMAIL = 'karnveer@scriza.in';
  const timestamp = Date.UTC(2026, 10, 7);
  const token = makeSession({ sub: 'google-subject-id', email: 'karnveer@scriza.in', now: timestamp });
  assert.equal(verifySession(token, timestamp)?.sub, 'google-subject-id');
  assert.equal(verifySession(token + 'x', timestamp), null);
  assert.equal(verifySession(token.slice(1), timestamp), null);
  assert.equal(verifySession(token, timestamp + 48 * 60 * 60 * 1000), null);
  const intruder = makeSession({ sub: 'other-sub', email: 'attacker@example.com', now: timestamp });
  assert.equal(verifySession(intruder, timestamp), null);
  assert.equal(readSession({ headers: { cookie: 'a=b; __Host-mini_session=' + token } })?.sub, 'google-subject-id');
});

test('same-origin POST policy requires matching HTTPS origin in production', () => {
  const oldNodeEnv = process.env.NODE_ENV;
  process.env.NODE_ENV = 'production';
  try {
    assert.equal(sameOrigin({ headers: { origin: 'https://mini-ai-gitkcoin.vercel.app', host: 'mini-ai-gitkcoin.vercel.app' } }), true);
    assert.equal(sameOrigin({ headers: { origin: 'https://other.site', host: 'mini-ai-gitkcoin.vercel.app' } }), false);
    assert.equal(sameOrigin({ headers: { origin: 'http://mini-ai-gitkcoin.vercel.app', host: 'mini-ai-gitkcoin.vercel.app' } }), false);
    assert.equal(sameOrigin({ headers: { host: 'mini-ai-gitkcoin.vercel.app' } }), false);
  } finally { if (oldNodeEnv === undefined) delete process.env.NODE_ENV; else process.env.NODE_ENV = oldNodeEnv; }
});

test('owner email normalizes case', () => {
  process.env.MINI_OWNER_EMAIL = '  Karnveer@Scriza.in ';
  assert.equal(ownerEmail(), 'karnveer@scriza.in');
});
