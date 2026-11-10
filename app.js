/* Mini — mobile app (installable PWA served by Vercel).
 * Sign in (Google or email code) → 6-step onboarding → Talk / Memories / You / Settings.
 * Live voice runs on the private Mini worker through MiniRealtimeSession.
 */
import {
  configureMiniIdentity, miniIdentity, googleMiniLogin, sendEmailMiniOtp, verifyEmailMiniOtp,
  signOutMini, readMiniProfile, saveMiniProfile, deleteMiniAccount,
  mindConsents, setMindConsent, mindFacts, keepMindFact, rejectMindFact, forgetMindFact, tellMind, mindSyncScore
} from './mini-supabase.js';
import { MiniRealtimeSession } from './mini-realtime-client.js';

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];
const app = $('#app');
const PREFS_KEY = 'mini-app-prefs-v1';
const ADULT_AGE = 18;

const state = {
  user: null,
  profile: null,          // row from mini_profiles
  draft: {},              // onboarding answers
  step: 0,
  mode: 'friend',
  session: null,
  wakeLock: null,
  installPrompt: null,
  prefs: loadPrefs(),
};

/* ---------- small helpers ---------- */
function loadPrefs() {
  try { return { captions: true, ...JSON.parse(localStorage.getItem(PREFS_KEY) || '{}') }; }
  catch { return { captions: true }; }
}
function savePrefs() { try { localStorage.setItem(PREFS_KEY, JSON.stringify(state.prefs)); } catch { /* private mode */ } }
let toastTimer = 0;
function toast(message) {
  const el = $('#toast');
  el.textContent = String(message || '').slice(0, 220);
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 4200);
}
function show(screen) {
  app.dataset.screen = screen;
  window.scrollTo(0, 0);
}
function friendlyError(error) {
  const msg = String(error?.message || error || 'Something went wrong.');
  if (/NotAllowedError|Permission denied|permission/i.test(msg))
    return 'Mini needs your microphone. Allow it in your browser settings, then try again.';
  if (/NotFoundError|no microphone|Requested device not found/i.test(msg)) return 'No microphone found on this device.';
  if (/network|Failed to fetch|unreachable/i.test(msg)) return 'Network problem. Check your connection and try again.';
  return msg.slice(0, 200);
}
function ageFrom(birthYear) {
  const y = Number(birthYear);
  return y ? new Date().getFullYear() - y : null;
}
function greetingWord() {
  const h = new Date().getHours();
  return h < 5 ? 'Up late' : h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening';
}

/* ---------- auth ---------- */
async function boot() {
  registerServiceWorker();
  setupInstall();
  bindStatic();
  let config;
  try { config = await configureMiniIdentity(); }
  catch { config = { enabled: false }; }
  if (!config.enabled) {
    show('welcome');
    $('#btn-google').disabled = true;
    $('#btn-email').disabled = true;
    toast('Sign-in is temporarily unavailable. Please try again soon.');
    return;
  }
  const client = miniIdentity();
  client.auth.onAuthStateChange((_event, session) => { void onUser(session?.user || null); });
  const { data } = await client.auth.getSession();
  await onUser(data?.session?.user || null);
  // Clean OAuth leftovers (?code=…) from the address bar.
  if (/[?&](code|error)=/.test(location.search)) history.replaceState(null, '', '/');
}

let userLoad = 0;
async function onUser(user) {
  const run = ++userLoad;
  if (!user) {
    stopTalking();
    state.user = null; state.profile = null;
    show('welcome');
    return;
  }
  if (state.user?.id === user.id && state.profile && app.dataset.screen === 'main') return;
  state.user = user;
  show('loading');
  let profile = null;
  try { profile = await readMiniProfile(); }
  catch (error) { toast('Could not load your profile: ' + friendlyError(error)); }
  if (run !== userLoad) return;
  state.profile = profile;
  const age = ageFrom(profile?.birth_year);
  if (!profile || !profile.birth_year || !profile.display_name) return startOnboarding(profile);
  if (age !== null && age < ADULT_AGE) return show('kids');
  enterMain();
}

/* ---------- onboarding ---------- */
const STEPS = [
  { key: 'name', q: 'What should I call you?', help: 'First name, nickname — whatever feels like you.', kind: 'text',
    placeholder: 'Your name', required: true, max: 80 },
  { key: 'birthYear', q: 'What year were you born?', help: 'So I can talk with you in the right way for your age.',
    kind: 'year', required: true },
  { key: 'relationship', q: 'What would you like me to be?', kind: 'choice', options: [
    ['friend', 'A best friend', 'Fun, warm, always up for a chat'],
    ['mentor', 'A mentor', 'Calm, practical, helps you grow'],
    ['both', 'A bit of both', 'Whatever you need that day']] },
  { key: 'tone', q: 'How should I talk with you?', kind: 'choice', options: [
    ['gentle', 'Gently', 'Soft and encouraging'],
    ['balanced', 'Balanced', 'Friendly and honest'],
    ['direct', 'Straight up', 'Short and to the point']] },
  { key: 'focus', q: "What's on your mind these days?", help: 'Work, studies, family, a goal — anything. You can skip this.',
    kind: 'area', placeholder: 'e.g. Preparing for exams, missing home…', max: 600 },
  { key: 'boundaries', q: 'Anything I should avoid talking about?', help: "Totally optional. I'll respect it.",
    kind: 'area', placeholder: "e.g. Please don't bring up my ex", max: 600, last: true },
];

function startOnboarding(profile) {
  state.draft = {
    name: profile?.display_name || '', birthYear: profile?.birth_year ? String(profile.birth_year) : '',
    relationship: profile?.companion_mode || 'friend', tone: profile?.tone || 'balanced',
    focus: profile?.focus || '', boundaries: profile?.boundaries || '', miniName: profile?.mini_name || 'Mini',
  };
  state.step = 0;
  renderStep();
  show('onboard');
}

function renderStep() {
  const step = STEPS[state.step];
  $('#ob-count').textContent = String(state.step + 1).padStart(2, '0') + ' / ' + String(STEPS.length).padStart(2, '0');
  $('#ob-bar').style.width = ((state.step + 1) / STEPS.length * 100) + '%';
  $('#ob-question').textContent = step.q;
  $('#ob-help').textContent = step.help || '';
  $('#ob-skip').classList.toggle('hidden', Boolean(step.required));
  $('#ob-next').textContent = step.last ? "Let's talk" : 'Next';
  const box = $('#ob-input');
  box.replaceChildren();
  const value = state.draft[step.key] || '';
  if (step.kind === 'text' || step.kind === 'year') {
    const input = document.createElement('input');
    input.id = 'ob-field';
    input.value = value;
    if (step.kind === 'year') {
      Object.assign(input, { inputMode: 'numeric', maxLength: 4, placeholder: 'e.g. 1998', autocomplete: 'bday-year' });
    } else {
      Object.assign(input, { maxLength: step.max, placeholder: step.placeholder, autocomplete: 'nickname' });
    }
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); nextStep(); } });
    box.append(input);
    setTimeout(() => input.focus(), 60);
  } else if (step.kind === 'area') {
    const area = document.createElement('textarea');
    Object.assign(area, { id: 'ob-field', rows: 4, maxLength: step.max, placeholder: step.placeholder, value });
    box.append(area);
  } else if (step.kind === 'choice') {
    for (const [val, title, sub] of step.options) {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'choice'; b.dataset.value = val;
      b.setAttribute('aria-pressed', String(value === val));
      const strong = document.createElement('strong'); strong.textContent = title;
      const small = document.createElement('small'); small.textContent = sub;
      b.append(strong, small);
      b.addEventListener('click', () => {
        state.draft[step.key] = val;
        $$('#ob-input .choice').forEach((c) => c.setAttribute('aria-pressed', String(c === b)));
      });
      box.append(b);
    }
  }
  if (step.last) {
    for (const [id, html] of [
      ['ob-consent', 'Remember my answers so Mini can get to know me. I can change or delete them anytime.'],
      ['ob-learn', 'Let Mini learn from our conversations — your day, people and goals — so it truly gets to know you. You review everything in Memories.'],
      ['ob-terms', 'I agree to the <a href="/terms.html" target="_blank">Terms</a> and <a href="/privacy.html" target="_blank">Privacy Policy</a>.']]) {
      const label = document.createElement('label'); label.className = 'consent';
      const cb = document.createElement('input'); cb.type = 'checkbox'; cb.id = id;
      const span = document.createElement('span'); span.innerHTML = html; // static, trusted text
      label.append(cb, span); box.append(label);
    }
  }
}

function readStepValue() {
  const step = STEPS[state.step];
  const field = $('#ob-field');
  if (field) state.draft[step.key] = field.value.trim();
  return state.draft[step.key] || '';
}

async function nextStep(skip = false) {
  const step = STEPS[state.step];
  const value = skip ? '' : readStepValue();
  if (skip) state.draft[step.key] = '';
  if (step.required && !value) return toast('Please answer this one so I know you.');
  if (step.key === 'birthYear') {
    const year = Number(value), now = new Date().getFullYear();
    if (!/^\d{4}$/.test(value) || year < 1920 || year > now - 5) return toast('Please enter a valid birth year.');
    if (now - year < ADULT_AGE) return show('kids'); // nothing is saved for under-18s yet
  }
  if (!step.last) { state.step++; renderStep(); return; }
  if (!$('#ob-consent').checked || !$('#ob-terms').checked)
    return toast('Please tick both boxes so Mini can remember you.');
  const btn = $('#ob-next'); btn.disabled = true;
  try {
    const d = state.draft;
    await saveMiniProfile({ name: d.name, miniName: d.miniName || 'Mini', relationship: d.relationship || 'friend',
      tone: d.tone || 'balanced', focus: d.focus || '', boundaries: d.boundaries || '', birthYear: d.birthYear }, true);
    state.profile = await readMiniProfile();
    if ($('#ob-learn').checked) {
      try { await setMindConsent('learn_from_conversations', true); await setMindConsent('proactive_followups', true); }
      catch (error) { toast('Could not save the learning choice: ' + friendlyError(error)); }
    }
    enterMain();
    setTimeout(() => toast("You're all set! Tap Mini whenever you want to talk."), 400);
  } catch (error) {
    toast('Could not save: ' + friendlyError(error));
  } finally { btn.disabled = false; }
}

/* ---------- main app ---------- */
function enterMain() {
  const p = state.profile || {};
  state.mode = p.companion_mode === 'mentor' ? 'mentor' : 'friend';
  $('#greet-time').textContent = greetingWord();
  $('#greet-name').textContent = 'Hi, ' + (p.display_name || 'friend');
  $('#set-email').textContent = state.user?.email || '';
  updateModeChip();
  fillYouForm();
  applyCaptions();
  setTalkState('idle');
  show('main');
  setTab('talk');
  void refreshMind();
}

/* ---------- mind: sync %, learning consent ---------- */
async function refreshMind() {
  try {
    const sync = await mindSyncScore();
    if (sync && sync.score !== undefined && sync.score !== null) {
      $('#sync-chip').textContent = 'Mini knows you ' + sync.score + '%';
      $('#sync-chip').classList.remove('hidden');
    }
  } catch { /* mind not available yet */ }
  try { $('#set-learn').checked = (await mindConsents()).has('learn_from_conversations'); }
  catch { $('#set-learn').disabled = true; }
}

function setTab(name) {
  $$('.tab').forEach((t) => {
    const on = t.dataset.tab === name;
    t.classList.toggle('active', on);
    if (on) t.setAttribute('aria-current', 'page'); else t.removeAttribute('aria-current');
  });
  $$('.panel').forEach((p) => { p.hidden = p.id !== 'p-' + name; });
  if (name === 'memories') void loadMemories();
  window.scrollTo(0, 0);
}

function updateModeChip() {
  $('#mode-chip').textContent = state.mode === 'mentor' ? '✦ Mentor' : '♡ Friend';
}

/* ---------- talk ---------- */
const TALK_TEXT = {
  idle: ['Tap Mini to talk', 'Tell me how your day went.'],
  checking: ['Getting ready…', ''],
  connecting: ['Connecting…', ''],
  authenticating: ['Connecting…', ''],
  queued: ['Mini is busy', ''],
  listening: ["I'm listening", 'Talk naturally. Tap Mini to interrupt.'],
  thinking: ['Thinking…', ''],
  speaking: ['Mini is talking', 'Just start talking to interrupt.'],
};

function setTalkState(status, sub) {
  const orb = $('#orb');
  const [title, defaultSub] = TALK_TEXT[status] || TALK_TEXT.idle;
  orb.dataset.state = status;
  $('#talk-status').textContent = title;
  $('#talk-sub').textContent = sub ?? defaultSub;
  const live = !['idle'].includes(status);
  const btn = $('#talk-btn');
  btn.textContent = live ? 'End conversation' : 'Start talking';
  btn.classList.toggle('end', live);
  orb.setAttribute('aria-label', live ? (status === 'speaking' ? 'Interrupt Mini' : 'Mini is listening') : 'Start talking with Mini');
}

async function preflight() {
  const { data } = await miniIdentity().auth.getSession();
  const token = data?.session?.access_token;
  if (!token) throw new Error('Please sign in again.');
  const res = await fetch('/api/voice/realtime-config', { headers: { Authorization: 'Bearer ' + token }, cache: 'no-store' });
  const body = await res.json().catch(() => ({}));
  if (res.status === 401) throw new Error('Please sign in again.');
  if (body.enabled) return;
  const reasons = {
    owner_only: "Mini's voice is opening to everyone very soon. Thanks for your patience!",
    not_invited: 'Mini is in a private preview right now. Your invite is coming soon!',
    email_unconfirmed: 'Please confirm your email address first.',
    age_confirmation_required: 'Mini is for adults right now. Mini for kids is coming soon.',
    nfc_gateway_not_ready: "Mini's voice is resting for maintenance. Please try again shortly.",
  };
  throw new Error(reasons[body.reason] || 'Mini is not available right now. Please try again soon.');
}

async function startTalking() {
  if (state.session) return;
  $('#cap-user').textContent = ''; $('#cap-mini').textContent = ''; $('#talk-meta').textContent = '';
  setTalkState('checking');
  try { await preflight(); }
  catch (error) { setTalkState('idle', friendlyError(error)); return; }
  const session = new MiniRealtimeSession({ onEvent: onTalkEvent, onClose: onTalkClosed });
  state.session = session;
  try {
    await session.start(state.mode);
  } catch (error) {
    session.fail?.(error);
    state.session = null;
    setTalkState('idle', friendlyError(error));
  }
}

function stopTalking() {
  const s = state.session;
  state.session = null;
  try { s?.stop(); } catch { /* already closed */ }
  releaseWakeLock();
}

function onTalkClosed() {
  state.session = null;
  releaseWakeLock();
  setTimeout(() => void refreshMind(), 45000);   // Mini finishes learning shortly after a talk
  if ($('#orb').dataset.state !== 'idle') setTalkState('idle', 'Tap Mini to talk again.');
}

let endsAt = 0, meterTimer = 0;
function onTalkEvent(event) {
  switch (event.type) {
    case 'ui.state':
      if (event.status === 'listening') { void keepAwake(); }
      if (TALK_TEXT[event.status]) setTalkState(event.status);
      break;
    case 'ui.queued':
      setTalkState('queued', event.message || 'Mini is talking with someone else. You will be connected automatically.');
      break;
    case 'ui.ending':
      setTalkState('idle', event.message || 'Conversation ended.');
      break;
    case 'ui.error':
      setTalkState('idle', friendlyError(event.message));
      break;
    case 'input.transcript.final':
      $('#cap-user').textContent = event.text || '';
      $('#cap-mini').textContent = '';
      break;
    case 'response.text.delta':
      $('#cap-mini').textContent += event.text || '';
      break;
    case 'ui.interrupted':
      setTalkState('listening', 'Go ahead, I\'m listening.');
      break;
    default: break;
  }
}

function applyCaptions() {
  $('#captions').classList.toggle('off', !state.prefs.captions);
  $('#set-captions').checked = state.prefs.captions;
}

async function keepAwake() {
  try { if ('wakeLock' in navigator && !state.wakeLock) state.wakeLock = await navigator.wakeLock.request('screen'); }
  catch { /* not supported or denied: fine */ }
}
function releaseWakeLock() {
  try { state.wakeLock?.release(); } catch { /* ignore */ }
  state.wakeLock = null;
}

/* ---------- memories (Mini's mind) ---------- */
const GROUPS = ['Identity', 'Physical', 'Health', 'Personality', 'Emotions', 'Learning', 'Communication', 'Language & culture',
  'Family', 'Relationships', 'Life history', 'Education', 'Skills', 'Career', 'Finances', 'Daily life', 'Interests',
  'Likes', 'Values', 'Spirituality', 'Goals', 'Dreams', 'Worries', 'Motivation', 'Decisions', 'Surroundings',
  'Digital life', 'Responsibilities', 'Experiences', 'How Mini helps'];
function factItem(f, actions) {
  const li = document.createElement('li'); li.className = 'mem-item' + (f.consent_status === 'pending' ? ' pending' : '');
  const p = document.createElement('p');
  const kind = document.createElement('span'); kind.className = 'mem-kind';
  kind.textContent = (GROUPS[f.group_id - 1] || 'Memory') + ' · ' + f.attribute_name;
  p.append(kind, document.createTextNode(f.value));
  li.append(p, actions(li));
  return li;
}
async function loadMemories() {
  try {
    const { known, pending } = await mindFacts();
    $('#noticed').classList.toggle('hidden', pending.length === 0);
    $('#noticed-list').replaceChildren(...pending.map((f) => factItem(f, (li) => {
      const row = document.createElement('div'); row.className = 'keep-actions';
      const keep = document.createElement('button'); keep.type = 'button'; keep.className = 'btn btn-primary'; keep.textContent = 'Keep';
      const no = document.createElement('button'); no.type = 'button'; no.className = 'btn btn-ghost'; no.textContent = 'Not true';
      keep.addEventListener('click', async () => {
        try { await keepMindFact(f.id); toast('Kept. Mini will remember.'); void loadMemories(); void refreshMind(); }
        catch (error) { toast(friendlyError(error)); }
      });
      no.addEventListener('click', async () => {
        try { await rejectMindFact(f.id); li.remove(); toast("Got it, Mini won't assume that."); void loadMemories(); }
        catch (error) { toast(friendlyError(error)); }
      });
      row.append(keep, no);
      return row;
    })));
    $('#mem-list').replaceChildren(...known.map((f) => factItem(f, (li) => {
      const del = document.createElement('button'); del.type = 'button'; del.className = 'mem-del';
      del.setAttribute('aria-label', 'Delete this memory'); del.textContent = '✕';
      del.addEventListener('click', async () => {
        try { await forgetMindFact(f.id); li.remove(); toast('Forgotten.'); checkEmpty(); void refreshMind(); }
        catch (error) { toast(friendlyError(error)); }
      });
      return del;
    })));
    checkEmpty();
  } catch (error) { toast('Could not load memories: ' + friendlyError(error)); }
}
function checkEmpty() { $('#mem-empty').classList.toggle('hidden', $('#mem-list').children.length > 0); }

/* ---------- you ---------- */
function fillYouForm() {
  const p = state.profile || {};
  $('#you-name').value = p.display_name || '';
  $('#you-mini').value = p.mini_name || 'Mini';
  $('#you-focus').value = p.focus || '';
  $('#you-bound').value = p.boundaries || '';
  for (const [name, val] of [['rel', p.companion_mode || 'friend'], ['tone', p.tone || 'balanced']]) {
    const el = document.querySelector(`input[name="${name}"][value="${val}"]`);
    if (el) el.checked = true;
  }
}

/* ---------- install / service worker ---------- */
function registerServiceWorker() {
  if (!('serviceWorker' in navigator) || location.hostname === 'localhost') return;
  window.addEventListener('load', () => { navigator.serviceWorker.register('/sw.js').catch(() => {}); });
}
function isStandalone() {
  return window.matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
}
function setupInstall() {
  const ios = /iphone|ipad|ipod/i.test(navigator.userAgent);
  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault(); state.installPrompt = e;
    $('#install-row').classList.remove('hidden');
  });
  if (ios && !isStandalone()) $('#install-row').classList.remove('hidden');
  window.addEventListener('appinstalled', () => { $('#install-row').classList.add('hidden'); toast('Mini is on your home screen!'); });
}

/* ---------- wiring ---------- */
function bindStatic() {
  $$('[data-go]').forEach((b) => b.addEventListener('click', () => show(b.dataset.go)));
  $('#btn-google').addEventListener('click', async () => {
    try { await googleMiniLogin(); } catch (error) { toast(friendlyError(error)); }
  });
  $('#btn-email').addEventListener('click', () => { show('email'); setTimeout(() => $('#email-input').focus(), 60); });

  let emailSent = false;
  $('#email-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = $('#email-submit'); btn.disabled = true;
    const email = $('#email-input').value.trim();
    try {
      if (!emailSent) {
        await sendEmailMiniOtp(email);
        emailSent = true;
        $('#code-field').classList.remove('hidden');
        btn.textContent = 'Sign in';
        $('#email-hint').textContent = 'Check your inbox for a code from Mini. It can take a minute.';
        setTimeout(() => $('#code-input').focus(), 60);
      } else {
        await verifyEmailMiniOtp(email, $('#code-input').value);
      }
    } catch (error) { toast(friendlyError(error)); }
    finally { btn.disabled = false; }
  });

  $('#ob-next').addEventListener('click', () => void nextStep(false));
  $('#ob-skip').addEventListener('click', () => void nextStep(true));
  $('#ob-back').addEventListener('click', () => {
    readStepValue();
    if (state.step === 0) return void signOutMini().catch(() => {});
    state.step--; renderStep();
  });
  $('#kids-signout').addEventListener('click', () => void signOutMini().catch(() => {}));

  $$('.tab').forEach((t) => t.addEventListener('click', () => setTab(t.dataset.tab)));
  $('#mode-chip').addEventListener('click', () => {
    if (state.session) return toast('End this conversation to switch.');
    state.mode = state.mode === 'mentor' ? 'friend' : 'mentor';
    updateModeChip();
    toast(state.mode === 'mentor' ? 'Mentor mode: calm and practical' : 'Friend mode: warm and playful');
  });

  $('#talk-btn').addEventListener('click', () => { if (state.session) stopTalking(); else void startTalking(); });
  $('#orb').addEventListener('click', () => {
    if (!state.session) return void startTalking();
    if ($('#orb').dataset.state === 'speaking') state.session.interrupt?.('user');
  });

  $('#mem-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const text = $('#mem-text').value.trim();
    if (!text) return;
    try {
      await tellMind({ kind: $('#mem-kind').value, text });
      $('#mem-text').value = '';
      toast("Got it, I'll remember that.");
      void loadMemories();
    } catch (error) { toast(friendlyError(error)); }
  });

  $('#you-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const p = state.profile || {};
    const pick = (name) => document.querySelector(`input[name="${name}"]:checked`)?.value;
    try {
      await saveMiniProfile({
        name: $('#you-name').value.trim(), miniName: $('#you-mini').value.trim() || 'Mini',
        relationship: pick('rel') || 'friend', tone: pick('tone') || 'balanced',
        focus: $('#you-focus').value.trim(), boundaries: $('#you-bound').value.trim(),
        birthYear: p.birth_year ? String(p.birth_year) : undefined,
      }, true);
      state.profile = await readMiniProfile();
      enterMain(); setTab('you');
      toast('Saved. Mini will use this next time you talk.');
    } catch (error) { toast('Could not save: ' + friendlyError(error)); }
  });

  $('#set-captions').addEventListener('change', (e) => { state.prefs.captions = e.target.checked; savePrefs(); applyCaptions(); });
  $('#set-learn').addEventListener('change', async (e) => {
    const on = e.target.checked;
    try {
      await setMindConsent('learn_from_conversations', on);
      await setMindConsent('proactive_followups', on);
      toast(on ? 'Mini will learn from your talks.' : "Mini won't learn from new talks. What it knows stays until you delete it.");
    } catch (error) { e.target.checked = !on; toast(friendlyError(error)); }
  });
  $('#btn-signout').addEventListener('click', async () => {
    stopTalking();
    try { await signOutMini(); } catch (error) { toast(friendlyError(error)); }
  });
  $('#btn-delete').addEventListener('click', async () => {
    if (!confirm('Delete your Mini account? Your profile and memories will be erased forever. This cannot be undone.')) return;
    stopTalking();
    try { await deleteMiniAccount(); toast('Your account was deleted.'); }
    catch (error) { toast('Could not delete: ' + friendlyError(error)); }
  });
  $('#btn-install').addEventListener('click', async () => {
    if (state.installPrompt) {
      state.installPrompt.prompt();
      await state.installPrompt.userChoice.catch(() => null);
      state.installPrompt = null;
    } else {
      $('#sheet-install').classList.remove('hidden');
    }
  });
  $('#sheet-close').addEventListener('click', () => $('#sheet-install').classList.add('hidden'));

  // Never keep the microphone open in the background.
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') stopTalking(); });
  window.addEventListener('pagehide', stopTalking);
}

void boot();
