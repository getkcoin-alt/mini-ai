import test from 'node:test';
import assert from 'node:assert/strict';
import handler from '../api/voice/realtime.js';

test('realtime gateway rejects non-GET with 405', async () => {
  let status, response;
  const headers = {};
  const res = {
    setHeader(k, v) { headers[k] = v; },
    status(s) { status = s; return this; },
    json(j) { response = j; return this; },
  };
  await handler({ method: 'POST', headers: {} }, res);
  assert.equal(status, 405);
  assert.equal(headers['Allow'], 'GET');
});

test('realtime gateway rejects non-upgrade requests with 426', async () => {
  let status, response;
  const res = {
    setHeader() {},
    status(s) { status = s; return this; },
    json(j) { response = j; return this; },
  };
  await handler({ method: 'GET', headers: {} }, res);
  assert.equal(status, 426);
  assert.match(response.error, /WebSocket required/);
});

test('realtime gateway fails closed when flags are disabled', async () => {
  const saved = { ...process.env };
  process.env.MINI_REALTIME_ENABLED = 'false';
  process.env.MINI_REALTIME_GATEWAY_READY = 'false';
  let status, response;
  const res = {
    setHeader() {},
    status(s) { status = s; return this; },
    json(j) { response = j; return this; },
  };
  try {
    await handler({ method: 'GET', headers: { upgrade: 'websocket' } }, res);
    assert.equal(status, 503);
    assert.match(response.error, /not ready yet/);
  } finally {
    process.env = saved;
  }
});
