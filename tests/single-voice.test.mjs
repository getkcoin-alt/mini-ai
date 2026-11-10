import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { makeSession, COOKIE_NAME } from '../api/_shared/auth.js';

function fakeRes() {
  return { code: 0, body: null, headers: {}, setHeader(k, v) { this.headers[k] = v; },
    status(c) { this.code = c; return this; }, json(b) { this.body = b; return this; } };
}

test('there is no web endpoint to upload or remove voice samples (Mini has one fixed voice)', () => {
  assert.equal(existsSync(new URL('../api/voice/sample.js', import.meta.url)), false);
});

test('frontend has no browser speech voice and no voice upload controls', () => {
  const js = readFileSync(new URL('../app.js', import.meta.url), 'utf8');
  const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
  assert.doesNotMatch(js, /speechSynthesis|SpeechSynthesisUtterance/);
  for (const id of ['voice-upload', 'voice-delete', 'voice-style', 'voice-reference-file']) {
    assert.doesNotMatch(html, new RegExp('id="' + id + '"'));
  }
});
