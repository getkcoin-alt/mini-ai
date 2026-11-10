import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { profileRowForUser } from '../mini-supabase.js';

const read = (p) => readFileSync(new URL('../' + p, import.meta.url), 'utf8');
const USER = '11111111-2222-4333-8444-555555555555';

test('app is installable: manifest, icons, iOS meta, service worker', () => {
  const html = read('index.html');
  for (const needle of ['rel="manifest"', 'apple-touch-icon', 'apple-mobile-web-app-capable', 'viewport-fit=cover'])
    assert.ok(html.includes(needle), needle);
  const manifest = JSON.parse(read('public/manifest.webmanifest'));
  assert.equal(manifest.display, 'standalone');
  assert.ok(manifest.icons.some((i) => i.sizes === '512x512' && i.purpose === 'maskable'));
  assert.ok(manifest.icons.some((i) => i.sizes === '192x192'));
  assert.match(read('app.js'), /serviceWorker\.register\('\/sw\.js'\)/);
});

test('service worker never caches API, sign-in or cross-origin traffic', () => {
  const sw = read('public/sw.js');
  assert.match(sw, /url\.origin !== self\.location\.origin/);
  assert.match(sw, /url\.pathname\.startsWith\('\/api\/'\)/);
  assert.match(sw, /req\.method !== 'GET'/);
});

test('onboarding has six steps starting with the name, and asks the birth year', () => {
  const app = read('app.js');
  const steps = app.slice(app.indexOf('const STEPS = ['), app.indexOf('];', app.indexOf('const STEPS = [')));
  assert.equal((steps.match(/\{ key: '/g) || []).length, 6);
  assert.match(steps, /key: 'name', q: 'What should I call you\?'/);
  assert.match(steps, /key: 'birthYear'/);
});

test('no demo codes, browser voices or legacy owner sign-in in the app', () => {
  const app = read('app.js') + read('index.html');
  assert.doesNotMatch(app, /123456|speechSynthesis|accounts\.google\.com\/gsi|DEMO_CODE/);
});

test('birth year: adults get age_confirmed_at, minors do not', () => {
  const now = '2026-11-10T00:00:00.000Z';
  const adult = profileRowForUser(USER, { name: 'A', birthYear: '1990' }, now);
  assert.equal(adult.birth_year, 1990);
  assert.equal(adult.age_confirmed_at, now);
  assert.ok(!adult.completed_keys.includes('birthYear'));
  const minor = profileRowForUser(USER, { name: 'B', birthYear: '2014' }, now);
  assert.equal(minor.birth_year, 2014);
  assert.ok(!('age_confirmed_at' in minor));
  assert.throws(() => profileRowForUser(USER, { birthYear: '1700' }), /birth year/);
});

test('legal pages exist and the crisis line is shown in settings', () => {
  assert.match(read('public/privacy.html'), /Privacy/);
  assert.match(read('public/terms.html'), /Terms/);
  assert.match(read('index.html'), /href="tel:14416"/);
});
