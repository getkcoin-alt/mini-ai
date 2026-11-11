// Super admin: choose where Mini's models run (our server or API providers),
// globally and per user. Shown only when /api/admin/infra says you are an admin.
// API keys live only on the worker; this page sees "key added: yes/no".

const PROVIDERS = { groq: 'Groq', gemini: 'Gemini', openrouter: 'OpenRouter' };
const VOICES = { auto: 'Follow the mode (API → Resemble)', server: 'Our server (Chatterbox)',
  elevenlabs: 'ElevenLabs', resemble: 'Resemble' };
const VOICE_NAMES = { elevenlabs: 'ElevenLabs', resemble: 'Resemble' };
let current = null;

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') node.className = v;
    else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const child of children) node.append(child);
  return node;
}

function option(value, label, selected) {
  const o = el('option', { value }, label);
  if (selected) o.selected = true;
  return o;
}

function readyText(ok) { return ok ? 'key added' : 'no key yet'; }

export function summarizePlan(choice, readiness) {
  const voice = choice.voice || 'auto';
  const hosted = VOICE_NAMES[voice] || (voice === 'auto' && choice.mode === 'api' ? 'Resemble' : null);
  const hostedKey = voice === 'elevenlabs' ? 'elevenlabs' : 'resemble';
  const voiceReady = readiness.voices ? readiness.voices[hostedKey] : readiness.tts;
  const missing = [];
  if (hosted && !voiceReady) missing.push('voice (' + hosted + ' key + voice id, or credit ran out)');
  const voiceText = hosted && voiceReady ? hosted + ' voice' : 'our server’s voice';
  if (choice.mode !== 'api') {
    const base = 'Local server: faster-whisper + Ollama, ' + voiceText + '.';
    return missing.length ? base + ' Not ready yet: ' + missing.join(', ') + '.' : base;
  }
  if (!readiness.stt) missing.push('hearing (Groq key)');
  if (!readiness.llm?.[choice.llm_provider]) missing.push('thinking (' + PROVIDERS[choice.llm_provider] + ' key)');
  return missing.length
    ? 'API mode, but these stay on the local server until keys are added: ' + missing.join(', ') + '.'
    : 'API mode: Groq hearing, ' + PROVIDERS[choice.llm_provider] + ' thinking, ' + voiceText + '.';
}

function keyRow(name, info, api, setMsg, health) {
  const secret = !/(UUID|VOICE_ID)$/.test(name);
  const input = el('input', { type: secret ? 'password' : 'text', autocomplete: 'off', spellcheck: 'false',
    maxlength: '400', placeholder: info.set ? 'Replace…' : (secret ? 'Paste key' : 'Paste id'), 'aria-label': info.label });
  if (name === 'MINI_RESEMBLE_VOICE_UUID') input.setAttribute('list', 'adm-voices');
  if (name === 'MINI_ELEVENLABS_VOICE_ID') input.setAttribute('list', 'adm-el-voices');
  const rest = health?.[name];
  const state = el('small', {}, info.set
    ? 'Added ' + (info.hint || '') + (info.source === 'server' ? ' · from server file' : ' · added here') +
      (rest ? ' · resting ' + Math.ceil(rest.resting_seconds / 60) + ' min (' + rest.why + ')' : '')
    : 'Not added');
  const saveBtn = el('button', { type: 'button', class: 'btn btn-ghost', onclick: async () => {
    if (!input.value.trim()) return;
    saveBtn.disabled = true;
    try { await api.post({ action: 'set_key', name, value: input.value.trim() }); input.value = ''; setMsg(info.label + ' saved.'); await api.refresh(); }
    catch (err) { setMsg(err.message); }
    saveBtn.disabled = false;
  } }, 'Save');
  const row = el('div', { class: 'adm-key' }, el('span', {}, el('strong', {}, info.label), state), input, saveBtn);
  const checkable = PROVIDERS[info.provider] || name === 'MINI_ELEVENLABS_API_KEY';
  if (info.set && checkable) {
    row.append(el('button', { type: 'button', class: 'btn-text', onclick: async () => {
      state.textContent = 'Checking…';
      try {
        const out = await api.post({ action: 'models', provider: info.provider, ...(PROVIDERS[info.provider] ? { slot: name } : {}) });
        state.textContent = out.ok ? 'Works ✓ · ' + out.models.length + (PROVIDERS[info.provider] ? ' models' : ' voices')
          : 'Not working: ' + out.error;
      } catch (err) { state.textContent = err.message; }
    } }, 'Check'));
  }
  if (info.source === 'admin') {
    row.append(el('button', { type: 'button', class: 'btn-text', 'aria-label': 'Remove ' + info.label, onclick: async () => {
      if (!confirm('Remove ' + info.label + '? Mini falls back to the server file or the local models.')) return;
      try { await api.post({ action: 'remove_key', name }); setMsg(info.label + ' removed.'); await api.refresh(); }
      catch (err) { setMsg(err.message); }
    } }, 'Remove'));
  }
  return row;
}

function fillList(list, models) {
  list.replaceChildren(...models.map((m) => el('option', { value: m.id }, m.name && m.name !== m.id ? m.name : '')));
}

function render(root, data, api) {
  const s = data.settings;
  const r = data.readiness;
  root.replaceChildren();
  const msg = el('p', { class: 'fine', role: 'status' });
  const setMsg = (text) => { msg.textContent = text; };

  const mode = el('select', { id: 'adm-mode', 'aria-label': 'Default infrastructure' },
    option('local', 'Our server (local models)', s.default.mode === 'local'),
    option('api', 'API models (no GPU needed)', s.default.mode === 'api'));
  const provider = el('select', { id: 'adm-provider', 'aria-label': 'LLM provider' },
    ...Object.entries(PROVIDERS).map(([k, label]) =>
      option(k, label + ' (' + readyText(r.llm?.[k]) + ')', s.default.llm_provider === k)));
  const chatList = el('datalist', { id: 'adm-chat-models' });
  const sttList = el('datalist', { id: 'adm-stt-models' });
  const voiceList = el('datalist', { id: 'adm-voices' });
  const elVoiceList = el('datalist', { id: 'adm-el-voices' });
  const voices = r.voices || { resemble: r.tts };
  const voice = el('select', { id: 'adm-voice', 'aria-label': 'Mini’s voice' },
    ...Object.entries(VOICES).map(([k, label]) => option(k,
      label + (VOICE_NAMES[k] ? ' (' + (voices[k] ? 'ready' : 'not ready') + ')' : ''), (s.default.voice || 'auto') === k)));
  const model = el('input', { id: 'adm-model', type: 'text', maxlength: '100', autocomplete: 'off', list: 'adm-chat-models',
    placeholder: data.providers?.[s.default.llm_provider]?.default_model || 'default model' });
  model.value = s.default.llm_model || '';
  const stt = el('input', { id: 'adm-stt', type: 'text', maxlength: '100', autocomplete: 'off', list: 'adm-stt-models',
    placeholder: data.stt_model || 'whisper-large-v3-turbo' });
  stt.value = s.default.stt_model || '';
  const modelNote = el('small', { class: 'fine' });
  const loadModels = async (which) => {
    const label = PROVIDERS[which] || VOICE_NAMES[which];
    modelNote.textContent = 'Loading ' + label + (PROVIDERS[which] ? ' models…' : ' voices…');
    try {
      const out = await api.post({ action: 'models', provider: which });
      if (!out.ok) { modelNote.textContent = label + ': ' + out.error; return; }
      if (which === 'elevenlabs') {
        fillList(elVoiceList, out.models.map((m) => ({ id: m.id, name: m.name + (m.mine ? ' · My Voices' : ' · stock') })));
        const mine = out.models.filter((m) => m.mine).length;
        modelNote.textContent = out.models.length + ' ElevenLabs voices loaded (' + mine + ' from My Voices): pick Mini’s voice in the ElevenLabs voice id box, then Save.';
        return;
      }
      if (which === 'resemble') { fillList(voiceList, out.models); modelNote.textContent = out.models.length + ' Resemble voices loaded: pick Mini’s voice in the voice id box.'; return; }
      const chat = out.models.filter((m) => m.kind !== 'speech' && m.free !== false);
      fillList(chatList, chat);
      if (which === 'groq') fillList(sttList, out.models.filter((m) => m.kind === 'speech'));
      modelNote.textContent = PROVIDERS[which] + ' key works · ' + chat.length + ' free models. Click the model box to choose.';
    } catch (err) { modelNote.textContent = err.message; }
  };
  provider.addEventListener('change', () => {
    model.placeholder = data.providers?.[provider.value]?.default_model || 'default model';
    chatList.replaceChildren();
    if (r.llm?.[provider.value]) loadModels(provider.value);
  });
  const plan = el('p', { class: 'fine', id: 'adm-plan' }, summarizePlan(s.default, r));
  const refreshPlan = () => { plan.textContent = summarizePlan({ mode: mode.value, llm_provider: provider.value, voice: voice.value }, r); };
  mode.addEventListener('change', refreshPlan);
  voice.addEventListener('change', refreshPlan);
  provider.addEventListener('change', refreshPlan);

  const users = el('div', { class: 'adm-users' });
  const addUserRow = (email = '', choice = {}) => {
    const e = el('input', { type: 'email', placeholder: 'user@email.com', 'aria-label': 'User email', maxlength: '254' });
    e.value = email;
    const m = el('select', { 'aria-label': 'Infrastructure for this user' },
      option('', 'Default', !choice.mode), option('local', 'Local', choice.mode === 'local'), option('api', 'API', choice.mode === 'api'));
    const v = el('select', { 'aria-label': 'Voice for this user' },
      option('', 'Default voice', !choice.voice),
      ...['server', 'elevenlabs', 'resemble'].map((k) => option(k, k === 'server' ? 'Server voice' : VOICE_NAMES[k], choice.voice === k)));
    const row = el('div', { class: 'adm-user' }, e, m, v,
      el('button', { type: 'button', class: 'btn-text', 'aria-label': 'Remove override', onclick: () => row.remove() }, '✕'));
    users.append(row);
  };
  for (const [email, choice] of Object.entries(s.users || {})) addUserRow(email, choice);

  const saveBtn = el('button', { type: 'button', class: 'btn btn-primary', onclick: async () => {
    const overrides = {};
    for (const row of users.querySelectorAll('.adm-user')) {
      const [e, m, v] = row.querySelectorAll('input, select');
      const choice = { ...(m.value ? { mode: m.value } : {}), ...(v.value ? { voice: v.value } : {}) };
      if (e.value.trim() && Object.keys(choice).length) overrides[e.value.trim().toLowerCase()] = choice;
    }
    const settings = { default: { mode: mode.value, llm_provider: provider.value, llm_model: model.value.trim(),
      stt_model: stt.value.trim(), voice: voice.value }, users: overrides };
    saveBtn.disabled = true;
    setMsg('Saving…');
    try { await api.post({ action: 'settings', settings }); setMsg('Saved. New conversations use this right away.'); await api.refresh(); }
    catch (err) { setMsg(err.message); }
    saveBtn.disabled = false;
  } }, 'Save');

  // One group per provider: every added key, plus one empty slot to add another.
  const keys = el('div', { class: 'adm-keys' });
  for (const [prov, title] of [['groq', 'Groq (hearing + thinking)'], ['gemini', 'Gemini (thinking)'],
                               ['openrouter', 'OpenRouter (thinking)'], ['elevenlabs', 'ElevenLabs (voice, one account)'],
                               ['resemble', 'Resemble (Mini’s voice, paid)']]) {
    const entries = Object.entries(data.keys || {}).filter(([, info]) => info.provider === prov);
    const shown = VOICE_NAMES[prov] ? entries
      : [...entries.filter(([, i]) => i.set), ...entries.filter(([, i]) => !i.set).slice(0, 1)];
    keys.append(el('h4', {}, title), ...shown.map(([name, info]) => keyRow(name, info, api, setMsg, data.key_health)));
  }

  const events = el('ul', { class: 'adm-events' });
  for (const ev of (data.events || []).slice(0, 8)) {
    const when = new Date(ev.at * 1000).toLocaleString();
    events.append(el('li', {}, when + ' · ' + ev.kind + ' · ' + ev.stage + (ev.provider ? ' → ' + ev.provider : '') +
      (ev.error ? ' (' + ev.error + ')' : '') + (ev.by ? ' by ' + ev.by : '')));
  }

  root.append(
    el('h3', {}, 'Super admin · Where Mini runs'),
    el('p', { class: 'hint' }, 'Same Mini everywhere: same mind, same voice, same safety. Only where the models run changes.'),
    el('label', { class: 'field' }, el('span', {}, 'Default for everyone'), mode),
    el('label', { class: 'field' }, el('span', {}, 'Thinking provider (API mode)'), provider),
    el('label', { class: 'field' }, el('span', {}, 'Thinking model (blank = default)'), model, chatList),
    el('label', { class: 'field' }, el('span', {}, 'Hearing model at Groq (blank = default)'), stt, sttList),
    el('label', { class: 'field' }, el('span', {}, 'Mini’s voice'), voice),
    el('p', { class: 'fine' }, 'Mini has one voice. If the hosted voice is not made from the same clip as our server’s voice, she sounds different whenever she falls back (credit used up, provider down). ElevenLabs’ free plan is about 20 minutes of speech a month and is not for commercial use.'),
    el('div', { class: 'adm-actions' },
      el('button', { type: 'button', class: 'btn btn-ghost', onclick: () => loadModels(provider.value) }, 'Load models'),
      el('button', { type: 'button', class: 'btn btn-ghost', onclick: () => loadModels('elevenlabs') }, 'Load ElevenLabs voices'),
      el('button', { type: 'button', class: 'btn btn-ghost', onclick: () => loadModels('resemble') }, 'Load Resemble voices')),
    modelNote,
    el('p', { class: 'fine' }, 'Hearing (' + readyText(r.stt) + ') · Voices: ElevenLabs ' + (voices.elevenlabs ? 'ready' : 'not ready') +
      ', Resemble ' + (voices.resemble ? 'ready' : 'not ready') + ' · API conversations now: ' + data.api_sessions + '/' + data.api_max_sessions),
    plan,
    el('div', { class: 'field' }, el('span', {}, 'Per-user overrides'), users,
      el('button', { type: 'button', class: 'btn btn-ghost', onclick: () => addUserRow() }, '+ Add user')),
    saveBtn,
    el('h3', {}, 'API keys'),
    el('p', { class: 'fine' }, 'Keys go straight to Mini’s private server and are never shown again, only the last 4 characters. Add up to 5 keys per provider: when one hits its free limit it rests and the next takes over. If every key of the chosen provider is resting, Mini uses a lighter free model, then the other providers, then our server.'),
    keys, voiceList, elVoiceList, msg,
    el('p', { class: 'fine' }, 'If a choice fails, Mini falls back on her own: API → our server, busy server → API. Recent events:'),
    events.childElementCount ? events : el('p', { class: 'fine' }, 'No events yet.'),
  );
  if (r.llm?.[s.default.llm_provider]) loadModels(s.default.llm_provider);
}

export async function initSuperAdmin(root, getToken) {
  if (!root) return;
  const call = async (method, body) => {
    const token = await getToken();
    if (!token) throw new Error('Please sign in again.');
    const res = await fetch('/api/admin/infra', {
      method, cache: 'no-store',
      headers: { Authorization: 'Bearer ' + token, ...(body ? { 'Content-Type': 'application/json' } : {}) },
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { const e = new Error(data.error || 'Could not reach Mini’s server.'); e.status = res.status; throw e; }
    return data;
  };
  try {
    current = await call('GET');
  } catch (err) {
    root.hidden = true;           // not an admin (403) or not signed in: show nothing
    if (err.status !== 403 && err.status !== 401) console.warn('super admin unavailable:', err.message);
    return;
  }
  const api = {
    post: (body) => call('POST', body),
    refresh: async () => { current = await call('GET'); render(root, current, api); },
  };
  render(root, current, api);
  root.hidden = false;
}
