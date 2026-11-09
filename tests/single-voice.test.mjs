import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import sample from '../api/voice/sample.js';
import { makeSession, COOKIE_NAME } from '../api/_shared/auth.js';

function fakeRes() {
  return { code: 0, body: null, headers: {}, setHeader(k, v) { this.headers[k] = v; },
    status(c) { this.code = c; return this; }, json(b) { this.body = b; return this; } };
}

test('voice sample upload and delete are refused without calling the worker', async () => {
  const savedSecret = process.env.MINI_SESSION_SECRET;
  const savedOwner = process.env.MINI_OWNER_EMAIL;
  process.env.MINI_SESSION_SECRET = 'a'.repeat(64);
  process.env.MINI_OWNER_EMAIL = 'owner@example.com';
  const cookie = COOKIE_NAME + '=' + makeSession({ sub: 'owner', email: 'owner@example.com' });
  let called = false;
  const realFetch = globalThis.fetch;
  globalThis.fetch = async () => { called = true; throw new Error('must not call worker'); };
  try {
    for (const method of ['POST', 'DELETE']) {
      const res = fakeRes();
      await sample({ method, headers: { origin: 'https://mini.example', host: 'mini.example', cookie }, body: { audio_base64: 'x'.repeat(2000), consent: true }, query: {} }, res);
      assert.equal(res.code, 403);
      assert.match(res.body.error, /one fixed voice/);
    }
  } finally {
    globalThis.fetch = realFetch;
    if (savedSecret === undefined) delete process.env.MINI_SESSION_SECRET; else process.env.MINI_SESSION_SECRET = savedSecret;
    if (savedOwner === undefined) delete process.env.MINI_OWNER_EMAIL; else process.env.MINI_OWNER_EMAIL = savedOwner;
  }
  assert.equal(called, false);
});

test('frontend has no browser speech voice and no voice upload controls', () => {
  const js = readFileSync(new URL('../app.js', import.meta.url), 'utf8');
  const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
  assert.doesNotMatch(js, /speechSynthesis|SpeechSynthesisUtterance/);
  for (const id of ['voice-upload', 'voice-delete', 'voice-style', 'voice-reference-file']) {
    assert.doesNotMatch(html, new RegExp('id="' + id + '"'));
  }
});
