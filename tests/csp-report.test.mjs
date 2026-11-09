import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import handler from '../api/csp-report.js';

test('csp report endpoint logs only directive and origin', () => {
  const logs = [];
  const warn = console.warn; console.warn = (...a) => logs.push(a.join(' '));
  try {
    const res = { code: 0, setHeader() {}, status(c) { this.code = c; return this; }, end() { return this; } };
    handler({ method: 'POST', body: { 'csp-report': { 'effective-directive': 'connect-src', 'blocked-uri': 'https://evil.example/path?token=secret' } } }, res);
    assert.equal(res.code, 204);
    assert.match(logs[0], /connect-src/);
    assert.match(logs[0], /https:\/\/evil\.example/);
    assert.doesNotMatch(logs[0], /secret|path/);
  } finally { console.warn = warn; }
});

test('vercel headers keep CSP report-only with the live endpoints allowed', () => {
  const cfg = JSON.parse(readFileSync(new URL('../vercel.json', import.meta.url), 'utf8'));
  const h = Object.fromEntries(cfg.headers[0].headers.map((x) => [x.key, x.value]));
  const csp = h['Content-Security-Policy-Report-Only'];
  assert.ok(csp);
  for (const needed of ["wss://api.themistones.com", "https://gkdaxtnlwojggdqitsex.supabase.co", "frame-ancestors 'none'", "object-src 'none'"])
    assert.ok(csp.includes(needed), needed);
  assert.equal(h['X-Frame-Options'], 'DENY');
});
