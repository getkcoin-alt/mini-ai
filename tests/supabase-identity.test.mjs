import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { profileRowForUser } from '../mini-supabase.js';

const OWNER = '01f4fa71-e66c-4302-b9fa-c4862eb94ea1';
test('profile row only uses validated user identity and approved fields', () => {
  const row = profileRowForUser(OWNER, {
    name: 'Alex', miniName: 'Mini', relationship: 'friend', tone: 'balanced',
    focus: 'Grow a business', boundaries: 'No spam', dangerous: 'ignored'
  }, '2026-11-08T00:00:00.000Z');
  assert.equal(row.user_id, OWNER);
  assert.equal(row.display_name, 'Alex');
  assert.equal(row.companion_mode, 'friend');
  assert.equal(row.consented_at, '2026-11-08T00:00:00.000Z');
  assert.ok(!('dangerous' in row));
});

test('invalid identity, mode, tone, or oversized text is rejected', () => {
  assert.throws(() => profileRowForUser('not-an-uuid', { name: 'Alex' }), /identity/);
  assert.throws(() => profileRowForUser(OWNER, { relationship: 'admin' }), /companion mode/);
  assert.throws(() => profileRowForUser(OWNER, { tone: 'root' }), /tone/);
  assert.throws(() => profileRowForUser(OWNER, { focus: 'x'.repeat(601) }), /Invalid focus/);
});

test('public config endpoint never returns worker or database service credentials', async () => {
  const config = await import('../api/auth/public-config.js');
  const saved = { ...process.env };
  process.env.MINI_SUPABASE_URL = 'https://gkdaxtnlwojggdqitsex.supabase.co';
  process.env.MINI_SUPABASE_PUBLISHABLE_KEY = 'sb_publishable_testvalue';
  process.env.MINI_WORKER_TOKEN = 'private-worker-secret';
  process.env.SUPABASE_SERVICE_ROLE_KEY = 'private-superuser-secret';
  process.env.MINI_SCRIWO_OTP_VERIFIED = 'false';
  const headers = {};
  let response;
  const res = {
    setHeader(k,v) { headers[k]=v; },
    status(code) { this.code=code; return this; },
    json(json) { response=json; return this; }
  };
  try {
    config.default({method:'GET'},res);
    assert.equal(res.code, 200);
    assert.equal(response.enabled,true);
    assert.equal(response.whatsappReady,false);
    assert.match(JSON.stringify(response), /sb_publishable_/);
    assert.doesNotMatch(JSON.stringify(response), /private-worker-secret|private-superuser-secret/);
    assert.equal(headers['Cache-Control'],'no-store');
  } finally {
    process.env = saved;
  }
});

test('unconfigured Supabase never enables real signup', async () => {
  const config = await import('../api/auth/public-config.js');
  const saved = { ...process.env };
  delete process.env.MINI_SUPABASE_URL;
  delete process.env.MINI_SUPABASE_PUBLISHABLE_KEY;
  let response;
  try {
    config.default({method:'GET'}, {
      setHeader(){}, status(){return this;},
      json(payload){response=payload;return this;}
    });
    assert.equal(response.enabled,false);
  } finally {
    process.env = saved;
  }
});

test('real auth UI gates mock OTP and only writes confirmed memories', () => {
  const src = readFileSync(new URL('../mini-identity-ui.js', import.meta.url),'utf8');
  assert.match(src, /e\.stopImmediatePropagation\(\)/);
  assert.match(src, /rememberMiniFact\(\{ kind: 'fact', content:.* consent: true \}\)/);
  assert.match(src, /sendWhatsAppMiniOtp\(/);
  assert.doesNotMatch(src, /123456/);
});
