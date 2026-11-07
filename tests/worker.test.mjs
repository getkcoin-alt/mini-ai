import test from 'node:test';
import assert from 'node:assert/strict';
import { workerConfigured, callWorker } from '../api/_shared/worker.js';

const saved = {
  MINI_WORKER_TOKEN: process.env.MINI_WORKER_TOKEN,
  MINI_WORKER_URL: process.env.MINI_WORKER_URL,
  NODE_ENV: process.env.NODE_ENV,
};
test.after(() => { for (const [key, value] of Object.entries(saved)) {
  if (value === undefined) delete process.env[key]; else process.env[key] = value;
} });

test('voice remains disabled with no private worker credentials', async () => {
  delete process.env.MINI_WORKER_URL;
  delete process.env.MINI_WORKER_TOKEN;
  assert.equal(workerConfigured(), false);
  await assert.rejects(callWorker('status', { method: 'GET' }), /not configured/i);
});

test('production rejects non-HTTPS worker URL and missing token', () => {
  process.env.NODE_ENV = 'production';
  process.env.MINI_WORKER_TOKEN = 'test-only-worker-private-token-32-characters';
  process.env.MINI_WORKER_URL = 'http://localhost:8765/';
  assert.equal(workerConfigured(), false);
  process.env.MINI_WORKER_URL = 'https://voice.example.com/';
  assert.equal(workerConfigured(), true);
  process.env.MINI_WORKER_TOKEN = 'short';
  assert.equal(workerConfigured(), false);
  process.env.MINI_WORKER_TOKEN = 'test-only-worker-private-token-32-characters';
  process.env.MINI_WORKER_URL = 'https://user:password@voice.example.com/';
  assert.equal(workerConfigured(), false);
});

test('worker proxy uses only server-held bearer token and fixed worker origin', async () => {
  process.env.NODE_ENV = 'production';
  process.env.MINI_WORKER_URL = 'https://voice.example.com/';
  process.env.MINI_WORKER_TOKEN = 'test-only-worker-private-token-32-characters';
  const oldFetch = globalThis.fetch;
  let called = 0;
  globalThis.fetch = async (url, init) => {
    called += 1;
    assert.equal(String(url), 'https://voice.example.com/v1/status');
    assert.equal(init.headers['x-mini-worker-token'], process.env.MINI_WORKER_TOKEN);
    assert.equal(init.cache, 'no-store');
    assert.equal(init.method, 'GET');
    return { ok: true, json: async () => ({ workerReady: true, referenceReady: false }) };
  };
  try {
    const result = await callWorker('status', { method: 'GET' });
    assert.deepEqual(result, { workerReady: true, referenceReady: false });
    assert.equal(called, 1);
  } finally { globalThis.fetch = oldFetch; }
});
