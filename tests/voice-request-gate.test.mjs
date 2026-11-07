import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createVoiceRequestGate, VoiceBusyError, voiceResponseError } from '../voice-request-gate.js';

test('only one expensive voice request may be active in a browser tab', async () => {
  const gate = createVoiceRequestGate();
  let completeFirst;
  let calls = 0;
  const first = gate.run(async () => {
    calls++;
    await new Promise(resolve => { completeFirst = resolve; });
    return 'voice ready';
  });
  assert.equal(gate.isBusy(), true);
  await assert.rejects(gate.run(async () => { calls++; }), VoiceBusyError);
  assert.equal(calls, 1, 'second model request must not start');
  completeFirst();
  assert.equal(await first, 'voice ready');
  assert.equal(gate.isBusy(), false);
  assert.equal(await gate.run(async () => 'next turn'), 'next turn');
});

test('the voice slot is released even when a network operation fails', async () => {
  const gate = createVoiceRequestGate();
  await assert.rejects(gate.run(async () => { throw new Error('network down'); }), /network down/);
  assert.equal(gate.isBusy(), false);
  assert.equal(await gate.run(async () => 42), 42);
});

test('server 429 yields a friendly busy message without an automatic retry', () => {
  const busy = voiceResponseError(429, { detail: 'Mini is completing another voice turn.' });
  assert.ok(busy instanceof VoiceBusyError);
  assert.equal(busy.status, 429);
  assert.match(busy.message, /finishing another voice response/i);
  const failure = voiceResponseError(503, { detail: 'Voice memory too low.' });
  assert.equal(failure.status, 503);
  assert.match(failure.message, /memory too low/i);
});

test('the stop control does not abort inference already running on the server', () => {
  const code = readFileSync(new URL('../app.js', import.meta.url), 'utf8');
  const fn = code.match(/function stopVoicePlayback\(\) \{([\s\S]*?)\n  \}/);
  assert.ok(fn, 'playback stop function must exist');
  assert.doesNotMatch(fn[1], /\.abort\(/, 'client abort leaves server-side inference running');
  assert.match(code, /voiceGate\.run\(/, 'heavy requests must use the single-turn gate');
  assert.match(code, /state\.suppressPendingVoice = true/, 'stop mutes pending replies');
});
