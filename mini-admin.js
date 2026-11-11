// Super admin: choose where Mini's models run (our server or API providers),
// globally and per user. Shown only when /api/admin/infra says you are an admin.
// API keys live only on the worker; this page sees "key added: yes/no".

const PROVIDERS = { groq: 'Groq', gemini: 'Gemini', openrouter: 'OpenRouter' };
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
  if (choice.mode !== 'api') return 'Local server: faster-whisper + Ollama + Chatterbox (as configured).';
  const missing = [];
  if (!readiness.stt) missing.push('hearing (Groq key)');
  if (!readiness.llm?.[choice.llm_provider]) missing.push('thinking (' + PROVIDERS[choice.llm_provider] + ' key)');
  if (!readiness.tts) missing.push('voice (Resemble key + voice id)');
  return missing.length
    ? 'API mode, but these stay on the local server until keys are added: ' + missing.join(', ') + '.'
    : 'API mode: Groq hearing, ' + PROVIDERS[choice.llm_provider] + ' thinking, hosted Mini voice.';
}

function keyRow(name, info, api, setMsg, health) {
  const secret = !/UUID$/.test(name);
  const input = el('input', { type: secret ? 'password' : 'text', autocomplete: 'off', spellcheck: 'false',
    maxlength: '400', placeholder: info.set ? 'Replace…' : (secret ? 'Paste key' : 'Paste id'), 'aria-label': info.label });
  if (name === 'MINI_RESEMBLE_VOICE_UUID') input.setAttribute('list', 'adm-voices');
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
  if (info.set && PROVIDERS[info.provider]) {
    row.append(el('button', { type: 'button', class: 'btn-text', onclick: async () => {
      state.textContent = 'Checking…';
      try {
        const out = await api.post({ action: 'models', provider: info.provider, slot: name });
        state.textContent = out.ok ? 'Works ✓ · ' + out.models.length + ' models' : 'Not working: ' + out.error;
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
  const model = el('input', { id: 'adm-model', type: 'text', maxlength: '100', autocomplete: 'off', list: 'adm-chat-models',
    placeholder: data.providers?.[s.default.llm_provider]?.default_model || 'default model' });
  model.value = s.default.llm_model || '';
  const stt = el('input', { id: 'adm-stt', type: 'text', maxlength: '100', autocomplete: 'off', list: 'adm-stt-models',
    placeholder: data.stt_model || 'whisper-large-v3-turbo' });
  stt.value = s.default.stt_model || '';
  const modelNote = el('small', { class: 'fine' });
  const loadModels = async (which) => {
    modelNote.textContent = 'Loading ' + (PROVIDERS[which] || 'Resemble') + ' models…';
    try {
      const out = await api.post({ action: 'models', provider: which });
      if (!out.ok) { modelNote.textContent = (PROVIDERS[which] || 'Resemble') + ': ' + out.error; return; }
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
  const refreshPlan = () => { plan.textContent = summarizePlan({ mode: mode.value, llm_provider: provider.value }, r); };
  mode.addEventListener('change', refreshPlan);
  provider.addEventListener('change', refreshPlan);

  const users = el('div', { class: 'adm-users' });
  const addUserRow = (email = '', choice = {}) => {
    const e = el('input', { type: 'email', placeholder: 'user@email.com', 'aria-label': 'User email', maxlength: '254' });
    e.value = email;
    const m = el('select', { 'aria-label': 'Infrastructure for this user' },
      option('local', 'Local', choice.mode === 'local'), option('api', 'API', choice.mode !== 'local'));
    const row = el('div', { class: 'adm-user' }, e, m,
      el('button', { type: 'button', class: 'btn-text', 'aria-label': 'Remove override', onclick: () => row.remove() }, '✕'));
    users.append(row);
  };
  for (const [email, choice] of Object.entries(s.users || {})) addUserRow(email, choice);

  const saveBtn = el('button', { type: 'button', class: 'btn btn-primary', onclick: async () => {
    const overrides = {};
    for (const row of users.querySelectorAll('.adm-user')) {
      const [e, m] = row.querySelectorAll('input, select');
      if (e.value.trim()) overrides[e.value.trim().toLowerCase()] = { mode: m.value };
    }
    const settings = { default: { mode: mode.value, llm_provider: provider.value, llm_model: model.value.trim(),
      stt_model: stt.value.trim() }, users: overrides };
    saveBtn.disabled = true;
    setMsg('Saving…');
    try { await api.post({ action: 'settings', settings }); setMsg('Saved. New conversations use this right away.'); await api.refresh(); }
    catch (err) { setMsg(err.message); }
    saveBtn.disabled = false;
  } }, 'Save');

  // One group per provider: every added key, plus one empty slot to add another.
  const keys = el('div', { class: 'adm-keys' });
  for (const [prov, title] of [['groq', 'Groq (hearing + thinking)'], ['gemini', 'Gemini (thinking)'],
                               ['openrouter', 'OpenRouter (thinking)'], ['resemble', 'Resemble (Mini’s voice, paid)']]) {
    const entries = Object.entries(data.keys || {}).filter(([, info]) => info.provider === prov);
    const shown = prov === 'resemble' ? entries
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
    el('div', { class: 'adm-actions' },
      el('button', { type: 'button', class: 'btn btn-ghost', onclick: () => loadModels(provider.value) }, 'Load models'),
      el('button', { type: 'button', class: 'btn btn-ghost', onclick: () => loadModels('resemble') }, 'Load voices')),
    modelNote,
    el('p', { class: 'fine' }, 'Hearing (' + readyText(r.stt) + ') · Voice: hosted Mini voice (' + readyText(r.tts) +
      ') · API conversations now: ' + data.api_sessions + '/' + data.api_max_sessions),
    plan,
    el('div', { class: 'field' }, el('span', {}, 'Per-user overrides'), users,
      el('button', { type: 'button', class: 'btn btn-ghost', onclick: () => addUserRow() }, '+ Add user')),
    saveBtn,
    el('h3', {}, 'API keys'),
    el('p', { class: 'fine' }, 'Keys go straight to Mini’s private server and are never shown again, only the last 4 characters. Add up to 5 keys per provider: when one hits its free limit it rests and the next takes over. If every key of the chosen provider is resting, Mini uses a lighter free model, then the other providers, then our server.'),
    keys, voiceList, msg,
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
