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

function render(root, data, save) {
  const s = data.settings;
  const r = data.readiness;
  root.replaceChildren();
  const mode = el('select', { id: 'adm-mode', 'aria-label': 'Default infrastructure' },
    option('local', 'Our server (local models)', s.default.mode === 'local'),
    option('api', 'API models (no GPU needed)', s.default.mode === 'api'));
  const provider = el('select', { id: 'adm-provider', 'aria-label': 'LLM provider' },
    ...Object.entries(PROVIDERS).map(([k, label]) =>
      option(k, label + ' (' + readyText(r.llm?.[k]) + ')', s.default.llm_provider === k)));
  const model = el('input', { id: 'adm-model', type: 'text', maxlength: '100', autocomplete: 'off',
    placeholder: data.providers?.[s.default.llm_provider]?.default_model || 'default model' });
  model.value = s.default.llm_model || '';
  provider.addEventListener('change', () => {
    model.placeholder = data.providers?.[provider.value]?.default_model || 'default model';
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

  const msg = el('p', { class: 'fine', role: 'status' });
  const saveBtn = el('button', { type: 'button', class: 'btn btn-primary', onclick: async () => {
    const overrides = {};
    for (const row of users.querySelectorAll('.adm-user')) {
      const [e, m] = row.querySelectorAll('input, select');
      if (e.value.trim()) overrides[e.value.trim().toLowerCase()] = { mode: m.value };
    }
    const settings = { default: { mode: mode.value, llm_provider: provider.value, llm_model: model.value.trim() }, users: overrides };
    saveBtn.disabled = true;
    msg.textContent = 'Saving…';
    try {
      await save(settings);
      msg.textContent = 'Saved. New conversations use this right away.';
    } catch (err) { msg.textContent = err.message; }
    saveBtn.disabled = false;
  } }, 'Save');

  const events = el('ul', { class: 'adm-events' });
  for (const ev of (data.events || []).slice(0, 8)) {
    const when = new Date(ev.at * 1000).toLocaleString();
    events.append(el('li', {}, when + ' · ' + ev.kind + ' · ' + ev.stage + (ev.provider ? ' → ' + ev.provider : '') +
      (ev.error ? ' (' + ev.error + ')' : '') + (ev.by ? ' by ' + ev.by : '')));
  }

  root.append(
    el('h3', {}, 'Super admin · Where Mini runs'),
    el('p', { class: 'hint' }, "Same Mini everywhere: same mind, same voice, same safety. Only where the models run changes."),
    el('label', { class: 'field' }, el('span', {}, 'Default for everyone'), mode),
    el('label', { class: 'field' }, el('span', {}, 'Thinking model (API mode)'), provider),
    el('label', { class: 'field' }, el('span', {}, 'Model name (blank = default)'), model),
    el('p', { class: 'fine' }, 'Hearing: Groq ' + data.stt_model + ' (' + readyText(r.stt) + ') · Voice: hosted Mini voice (' +
      readyText(r.tts) + ') · API conversations now: ' + data.api_sessions + '/' + data.api_max_sessions),
    plan,
    el('div', { class: 'field' }, el('span', {}, 'Per-user overrides'), users,
      el('button', { type: 'button', class: 'btn btn-ghost', onclick: () => addUserRow() }, '+ Add user')),
    saveBtn, msg,
    el('p', { class: 'fine' }, 'If a choice fails, Mini falls back on her own: API → our server, busy server → API. Recent events:'),
    events.childElementCount ? events : el('p', { class: 'fine' }, 'No events yet.'),
  );
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
  const save = async (settings) => {
    await call('POST', { settings });
    current = await call('GET');
    render(root, current, save);
  };
  render(root, current, save);
  root.hidden = false;
}
