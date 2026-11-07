/* Mini AI — frontend-only interactive prototype.
 * Important: browser speech APIs and scripted demo responses are NOT an AI backend,
 * and the Google/email/WhatsApp flows below DO NOT authenticate real users.
 */
(function () {
  'use strict';

  const STORAGE_KEY = 'mini-ai-design-preview-v1';
  const DEMO_CODE = '123456';
  const questions = [
    { key: 'name', question: 'What should I call you?', help: 'First names, nicknames, anything that feels like you.', placeholder: 'You can say “Call me Alex” or just “Alex”.', kind: 'text' },
    { key: 'miniName', question: 'And what would you like to call me?', help: 'Mini works. Or give me a name that feels like ours.', placeholder: 'Mini, Momo, Spark — your call.', kind: 'text' },
    { key: 'relationship', question: 'What do you need from me most?', help: 'There is no wrong choice. You can always switch later.', kind: 'choice', choices: [{ value: 'friend', icon: '♡', label: 'A best friend' }, { value: 'mentor', icon: '✦', label: 'A mentor' }, { value: 'both', icon: '☯', label: 'A bit of both' }] },
    { key: 'tone', question: 'How should I talk with you?', help: 'Think of how someone close to you would talk when it matters.', kind: 'choice', choices: [{ value: 'gentle', icon: '❀', label: 'Gentle & kind' }, { value: 'balanced', icon: '◎', label: 'Warm & practical' }, { value: 'direct', icon: '↗', label: 'Direct & honest' }] },
    { key: 'focus', question: "What's taking up space in your mind lately?", help: 'A dream, a project, a worry, or anything you want me to understand.', placeholder: '“I want to change careers, but I keep putting it off...”', kind: 'text' },
    { key: 'boundaries', question: 'Is there anything you want me to respect?', help: "I can listen, challenge, or give you space. You're in charge.", placeholder: '“Be honest with me, but don’t push when I say stop.”', kind: 'text' }
  ];
  const defaults = { name: '', miniName: 'Mini', relationship: 'both', tone: 'balanced', focus: '', boundaries: '' };
  const state = { profile: { ...defaults }, completed: {}, hasTalked: false, step: 0, auth: 'google', page: 'today', mode: 'friend', isListening: false, recognizer: null, autoSpeak: true, voiceOutput: true, captions: true, lastReply: '', previewGuest: true, demoExploration: false, voiceStatus: { authReady: false, ownerSignedIn: false, ttsReady: false, agentReady: false }, chosenVoiceId: '', voiceAbort: null, voiceAudio: null, voiceAudioUrl: null, liveConversation: null, liveConnecting: false };

  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => Array.from(document.querySelectorAll(selector));
  const text = (selector, value) => { const el = $(selector); if (el) el.textContent = value; };
  const show = (selector, visible) => { const el = $(selector); if (el) el.classList.toggle('hidden', !visible); };
  function toast(message) {
    const el = $('#toast');
    el.textContent = message;
    el.classList.add('show');
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => el.classList.remove('show'), 3900);
  }
  function save() {
    if (state.demoExploration) return;
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ profile: state.profile, completed: state.completed, hasTalked: state.hasTalked }));
    } catch (_) { toast('This browser is not allowing local preview storage.'); }
  }
  function load() {
    try {
      const data = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null');
      if (data && data.profile && typeof data.profile === 'object') {
        Object.keys(defaults).forEach((key) => {
          if (typeof data.profile[key] === 'string' && data.profile[key].length <= 2000) state.profile[key] = data.profile[key];
        });
        if (data.completed && typeof data.completed === 'object') {
          questions.forEach((q) => { if (data.completed[q.key] === true) state.completed[q.key] = true; });
        }
        state.hasTalked = data.hasTalked === true;
        return true;
      }
    } catch (_) { /* corrupted preview data should not block launch */ }
    return false;
  }
  function progress() {
    const weights = { name: 15, miniName: 10, relationship: 20, tone: 15, focus: 20, boundaries: 10 };
    let score = 0;
    Object.keys(weights).forEach((k) => { if (state.completed[k] && String(state.profile[k] || '').trim()) score += weights[k]; });
    if (state.hasTalked) score += 10;
    return Math.min(100, score);
  }
  function nameOr(fallback) { return String(state.profile.name || '').trim() || fallback; }
  function miniOr() { return String(state.profile.miniName || 'Mini').trim() || 'Mini'; }
  function roleLabel(value) { return ({ friend: 'A real-talk best friend', mentor: 'A calm, practical mentor', both: 'Best friend + mentor' })[value] || 'Best friend + mentor'; }
  function toneLabel(value) { return ({ gentle: 'Gentle & encouraging', balanced: 'Warm & practical', direct: 'Straightforward & honest' })[value] || 'Warm & practical'; }
  function normalizeAnswer(value) {
    let v = String(value || '').trim().replace(/\s+/g, ' ');
    v = v.replace(/^(my name is|you can call me|call me|i want you to call me|i'd like you to call me)\s+/i, '');
    return v;
  }
  function previewSummary(q, value) {
    if (!value) return '';
    const clean = String(value).trim().replace(/\s+/g, ' ');
    if (q.key === 'name') return 'I should call you ' + normalizeAnswer(clean).slice(0, 72) + '.';
    if (q.key === 'miniName') return 'You would like to call your companion ' + normalizeAnswer(clean).slice(0, 72) + '.';
    if (q.key === 'focus') return 'Something on your mind: ' + clean.slice(0, 260);
    if (q.key === 'boundaries') return 'A boundary or preference to respect: ' + clean.slice(0, 260);
    return clean;
  }
  function screen(id) {
    $$('.screen').forEach((el) => el.classList.toggle('active', el.id === 'screen-' + id));
    document.body.classList.toggle('app-open', id === 'home');
    window.scrollTo({ top: 0, behavior: 'instant' });
    if (id === 'home') refreshHome();
  }
  function begin() {
    screen('auth');
    selectAuth('google');
  }
  function selectAuth(method) {
    state.auth = method;
    $$('.auth-tab').forEach((el) => { const active = el.dataset.authMethod === method; el.classList.toggle('active', active); el.setAttribute('aria-selected', String(active)); });
    ['google', 'email', 'whatsapp'].forEach((m) => show('#auth-' + m, m === method));
  }
  function emailFlow(event) {
    event.preventDefault();
    const address = $('#email-address').value.trim();
    if (!$('#email-address').checkValidity() || !address) return toast('Enter a valid email address for this UI preview.');
    const wrap = $('#email-code-wrap');
    if (wrap.classList.contains('hidden')) {
      wrap.classList.remove('hidden');
      text('#email-action', 'Continue with preview code ↗');
      toast('Demo code: 123456. No email was sent.');
      return;
    }
    if ($('#email-code').value.trim() !== DEMO_CODE) return toast('Use 123456 to preview the verification step.');
    toast('Preview code accepted. Identity is NOT verified.');
    startSetup();
  }
  function whatsappFlow(event) {
    event.preventDefault();
    const phone = $('#wa-phone').value.replace(/\D/g, '');
    if (phone.length !== 10) return toast('Enter a 10-digit Indian mobile number for this UI preview.');
    const wrap = $('#wa-code-wrap');
    if (wrap.classList.contains('hidden')) {
      wrap.classList.remove('hidden');
      text('#wa-action', 'Continue with preview code ↗');
      toast('Demo code: 123456. No WhatsApp message was sent.');
      return;
    }
    if ($('#wa-code').value.trim() !== DEMO_CODE) return toast('Use 123456 to preview the verification step.');
    toast('Preview code accepted. Identity is NOT verified.');
    startSetup();
  }
  function browserSpeak(message) {
    if (!state.voiceOutput || !('speechSynthesis' in window) || !message) return false;
    try {
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(String(message).replace(/[✦♡◎]/g, ''));
      utterance.rate = .98; utterance.pitch = 1.07; utterance.volume = 1;
      const voices = window.speechSynthesis.getVoices();
      const english = voices.find((v) => v.lang && v.lang.toLowerCase().startsWith('en') && /natural|premium|female|samantha|google/i.test(v.name))
        || voices.find((v) => v.lang && v.lang.toLowerCase().startsWith('en'));
      if (english) utterance.voice = english;
      utterance.onstart = () => $('#app-orb')?.classList.add('speaking');
      utterance.onend = () => $('#app-orb')?.classList.remove('speaking');
      utterance.onerror = () => $('#app-orb')?.classList.remove('speaking');
      window.speechSynthesis.speak(utterance);
      return true;
    } catch (_) { return false; }
  }
  function listen(target) {
    if (state.liveConversation) return toast('End the live ElevenLabs call before using the browser microphone.');
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      toast('Live speech recognition is not supported in this browser. You can still type.');
      text('#setup-voice-info', 'This browser does not support speech recognition. Please type your answer.');
      return;
    }
    if (state.recognizer) {
      state.recognizer.abort();
      state.recognizer = null;
      state.isListening = false;
      updateListening(false);
      return;
    }
    try {
      stopVoicePlayback();
      const recognition = new SpeechRecognition();
      state.recognizer = recognition;
      recognition.lang = navigator.language || 'en-IN';
      recognition.interimResults = true;
      recognition.continuous = false;
      recognition.maxAlternatives = 1;
      let captured = '';
      recognition.onstart = () => { state.isListening = true; updateListening(true); };
      recognition.onresult = (event) => {
        let partial = '';
        for (let i = event.resultIndex; i < event.results.length; i++) {
          const candidate = event.results[i][0]?.transcript || '';
          if (event.results[i].isFinal) captured += candidate + ' ';
          else partial += candidate;
        }
        const value = (captured + partial).trim();
        if (target === 'setup') {
          $('#question-answer').value = value;
          updateSummary();
        } else {
          text('#user-transcript', value || 'Listening...');
          if ($('#type-input')) $('#type-input').value = value;
        }
      };
      recognition.onerror = (event) => {
        if (event.error !== 'aborted') toast('Microphone unavailable (' + event.error + '). Try typing instead.');
      };
      recognition.onend = () => {
        state.recognizer = null; state.isListening = false; updateListening(false);
        if (target === 'home' && captured.trim()) handleMessage(captured.trim());
      };
      recognition.start();
    } catch (_) {
      state.recognizer = null; state.isListening = false; updateListening(false);
      toast('Could not start the microphone. Check browser permissions.');
    }
  }
  function updateListening(active) {
    $('#talk-button')?.classList.toggle('listening', active);
    text('#talk-icon', active ? '■' : '🎙');
    text('#voice-state', active ? 'Listening to you...' : 'Ready when you are.');
    if (!state.liveConversation && !state.liveConnecting) text('#voice-helper', active ? 'Speak naturally. Tap the mic to stop.' : 'Tap the microphone to talk · Browser speech preview');
    text('#setup-voice-info', active ? '🎙 Listening... speak at your own pace.' : '🎙 Microphone support depends on your browser. Typing always works.');
    text('#speak-answer span', active ? 'Stop listening' : 'Speak instead');
  }
  function startSetup() {
    state.demoExploration = false;
    state.step = 0;
    screen('setup');
    renderQuestion(true);
  }
  function renderQuestion(announce) {
    const q = questions[state.step];
    text('#step-counter', String(state.step + 1).padStart(2, '0') + ' / ' + String(questions.length).padStart(2, '0'));
    $('#step-progress-bar').style.width = Math.round(((state.step + 1) / questions.length) * 100) + '%';
    text('#question-text', q.question);
    text('#question-help', q.help);
    text('#question-speaker', miniOr().toLowerCase() + ' is curious');
    text('#next-question', state.step === questions.length - 1 ? 'Meet your Mini ↗' : 'Save & continue ↗');
    show('#answer-wrap', q.kind === 'text');
    show('#question-choices', q.kind === 'choice');
    if (q.kind === 'text') {
      $('#question-answer').placeholder = q.placeholder || 'Say it your way...';
      $('#question-answer').value = state.completed[q.key] ? (state.profile[q.key] || '') : '';
    } else {
      const container = $('#question-choices');
      container.replaceChildren();
      q.choices.forEach((c) => {
        const button = document.createElement('button');
        button.className = 'choice' + (state.completed[q.key] && state.profile[q.key] === c.value ? ' active' : '');
        button.type = 'button';
        button.dataset.choice = c.value;
        const symbol = document.createElement('span');
        symbol.textContent = c.icon;
        const label = document.createElement('strong');
        label.textContent = c.label;
        button.append(symbol, label);
        button.addEventListener('click', () => {
          state.profile[q.key] = c.value;
          state.completed[q.key] = true;
          container.querySelectorAll('.choice').forEach((item) => item.classList.toggle('active', item === button));
          refreshProfilePreview();
        });
        container.append(button);
      });
    }
    updateSummary();
    refreshProfilePreview();
    if (announce && state.autoSpeak) speak(q.question);
  }
  function updateSummary() {
    const q = questions[state.step];
    if (q.kind !== 'text') { show('#summary-preview', false); return; }
    const value = $('#question-answer').value.trim();
    show('#summary-preview', Boolean(value));
    if (value) text('#summary-text', previewSummary(q, value));
  }
  function saveStep(skip) {
    const q = questions[state.step];
    if (!skip) {
      if (q.kind === 'text') {
        let value = $('#question-answer').value.trim();
        if (q.key === 'name' || q.key === 'miniName') value = normalizeAnswer(value).slice(0, 72);
        else value = value.slice(0, 800);
        if (!value) return toast('Give it a try, or choose “I’ll tell you later”.');
        state.profile[q.key] = value;
        state.completed[q.key] = true;
      } else if (!state.completed[q.key]) return toast('Pick the answer that feels right, or skip for now.');
    }
    if (skip && !state.completed[q.key]) {
      state.profile[q.key] = defaults[q.key];
    }
    save();
    if (state.step >= questions.length - 1) return enterHome();
    state.step++;
    renderQuestion(true);
  }
  function refreshProfilePreview() {
    const p = state.profile;
    text('#profile-name', state.completed.name ? nameOr('You') : 'Getting acquainted...');
    text('#profile-mini', state.completed.miniName ? miniOr() : 'Mini');
    text('#profile-mode', state.completed.relationship ? roleLabel(p.relationship) : 'Your personal companion');
    text('#profile-tone', state.completed.tone ? toneLabel(p.tone) : 'Still discovering');
    text('#profile-goal', state.completed.focus ? p.focus.slice(0, 110) : "We'll find out together.");
    const percent = progress();
    text('#setup-sync-text', percent + '%');
    $('#setup-sync-bar').style.width = percent + '%';
  }
  function enterHome() {
    state.mode = state.profile.relationship === 'mentor' ? 'mentor' : 'friend';
    screen('home');
    setPage('today');
    refreshHome();
    save();
  }
  function refreshHome() {
    const p = state.profile;
    const percent = progress();
    text('#home-greeting', 'Hey, ' + nameOr('you') + '. I’m right here.');
    text('#mini-display-name', miniOr().toLowerCase());
    text('#sidebar-sync', percent + '% synced');
    text('#home-sync', percent + '%');
    $('#home-sync-bar').style.width = percent + '%';
    $('#sidebar-sync-bar').style.width = percent + '%';
    text('#sidebar-name', nameOr('Your space'));
    text('#user-initial', nameOr('Y').charAt(0).toUpperCase());
    text('#app-initial', nameOr('Y').charAt(0).toUpperCase());
    text('#sync-message', percent >= 80 ? "You've shared a lot of useful context. Long-term memory is the next step." : percent >= 45 ? "You're shaping Mini's tone and priorities. Keep going when you feel ready." : 'Share a few preferences to shape your companion.');
    text('#unlock-vibe', percent >= 20 ? '✓' : '○');
    text('#unlock-mode', state.completed.relationship ? '✓' : '○');
    text('#unlock-context', state.completed.focus && state.completed.boundaries ? '✓' : '○');
    $$('.mode-switch [data-mode]').forEach((el) => el.classList.toggle('active', el.dataset.mode === state.mode));
    $('#show-captions').checked = state.captions;
    $('#voice-output').checked = state.voiceOutput;
    $('#transcript-panel').classList.toggle('hidden', !state.captions);
    text('#toggle-captions', state.captions ? '◫ Captions on' : '◫ Captions off');
    $('#toggle-captions').setAttribute('aria-pressed', String(state.captions));
  }
  function setPage(page) {
    state.page = page;
    $$('.app-page').forEach((el) => el.classList.toggle('active', el.id === 'app-page-' + page));
    $$('[data-app-page]').forEach((el) => el.classList.toggle('active', el.dataset.appPage === page));
    text('#current-page-label', ({ today: 'MY SPACE', profile: 'OUR DYNAMIC', memory: 'MEMORIES', devices: 'DEVICES', settings: 'PREFERENCES' })[page] || 'MY SPACE');
    if (page === 'profile') fillProfileEdit();
    window.scrollTo({ top: 0, behavior: 'instant' });
  }
  function fillProfileEdit() {
    const p = state.profile;
    $('#edit-name').value = p.name;
    $('#edit-mini-name').value = p.miniName;
    $('#edit-mode').value = p.relationship;
    $('#edit-tone').value = p.tone;
    $('#edit-focus').value = p.focus;
    $('#edit-boundaries').value = p.boundaries;
  }
  function saveProfile(event) {
    event.preventDefault();
    const next = {
      name: $('#edit-name').value.trim().slice(0, 72),
      miniName: $('#edit-mini-name').value.trim().slice(0, 72),
      relationship: $('#edit-mode').value,
      tone: $('#edit-tone').value,
      focus: $('#edit-focus').value.trim().slice(0, 800),
      boundaries: $('#edit-boundaries').value.trim().slice(0, 800)
    };
    if (!next.name || !next.miniName) return toast('Please add a name for both you and Mini.');
    state.profile = next;
    Object.keys(next).forEach((key) => { state.completed[key] = Boolean(next[key]); });
    save(); refreshHome();
    toast('Preferences saved locally in this browser.');
  }
  function previewReply(message) {
    const cleaned = message.toLowerCase();
    const mode = state.mode;
    const person = nameOr('friend').split(' ')[0].slice(0, 28);
    if (/hello|hey|hi\b|good morning|good evening/.test(cleaned)) {
      return mode === 'mentor' ? 'Hey ' + person + '. What would make today feel like progress?' : 'Hey ' + person + '! So good to hear you. What’s happening?';
    }
    if (/anxious|sad|worried|stressed|alone|scared|overwhelmed|not okay/.test(cleaned)) {
      return mode === 'mentor' ? 'I hear you. What’s the one part of this we can actually change today?' : 'That sounds like a lot to carry. Want to tell me what happened?';
    }
    if (/goal|work|study|business|career|project|deadline|focus|productive/.test(cleaned)) {
      return mode === 'mentor' ? 'Okay, let’s make this practical. What’s the smallest next step you could do in twenty minutes?' : 'Ooh, we have a mission. What part are you most excited about?';
    }
    if (/thank|love|friend/.test(cleaned)) return mode === 'mentor' ? 'Glad to be useful. What shall we tackle next?' : 'Aw, I’m glad we’re talking. What else is on your mind?';
    if (/who are you|what are you|real/.test(cleaned)) return 'I’m Mini, your AI companion. This is a scripted voice preview, but the real version will learn with your permission.';
    return mode === 'mentor' ? 'I’m listening. What matters most about that, and what would a good outcome look like?' : 'Wait, tell me more. What happened next?';
  }
  function handleMessage(message) {
    const value = String(message || '').trim().slice(0, 500);
    if (!value) return;
    const reply = previewReply(value);
    state.lastReply = reply;
    state.hasTalked = true;
    text('#user-transcript', value);
    text('#mini-transcript', '“' + reply + '”');
    text('#voice-state', 'Here with you.');
    $('#type-input').value = '';
    save(); refreshHome();
    void speak(reply);
  }
  function demoExplore() {
    if (!state.profile.name) {
      state.profile.name = 'Explorer';
      state.profile.miniName = 'Mini';
      state.profile.relationship = 'both';
      state.profile.tone = 'balanced';
    }
    state.demoExploration = true;
    state.mode = 'friend';
    screen('home'); setPage('today');
    toast('Exploring a design demo. Nothing here is a connected AI service.');
  }
  function resetData() {
    if (!confirm('Clear the local preview profile and restart? This cannot be undone.')) return;
    try { localStorage.removeItem(STORAGE_KEY); } catch (_) {}
    state.profile = { ...defaults };
    state.completed = {};
    state.hasTalked = false;
    state.lastReply = '';
    state.demoExploration = false;
    if ('speechSynthesis' in window) window.speechSynthesis.cancel();
    screen('welcome');
    toast('Local preview data cleared.');
  }

  // Navigation
  ['#header-start', '#hero-start', '#footer-start'].forEach((sel) => $(sel).addEventListener('click', begin));
  $('#brand-home').addEventListener('click', (event) => { event.preventDefault(); screen('welcome'); });
  $('#hero-preview').addEventListener('click', demoExplore);
  $('#auth-back').addEventListener('click', () => screen('welcome'));
  $$('.auth-tab').forEach((el) => el.addEventListener('click', () => selectAuth(el.dataset.authMethod)));
  $('#google-signin').addEventListener('click', () => toast('Google login requires the OAuth client configured in Vercel. Continue in demo mode until then.'));
  $('#auth-email').addEventListener('submit', emailFlow);
  $('#auth-whatsapp').addEventListener('submit', whatsappFlow);
  $('#continue-demo').addEventListener('click', startSetup);
  $('#setup-back').addEventListener('click', () => { if (state.step === 0) screen('auth'); else { state.step--; renderQuestion(false); } });
  $('#skip-question').addEventListener('click', () => saveStep(true));
  $('#next-question').addEventListener('click', () => saveStep(false));
  $('#listen-question').addEventListener('click', () => { void speak(questions[state.step].question); });
  $('#speak-answer').addEventListener('click', () => listen('setup'));
  $('#question-answer').addEventListener('input', updateSummary);
  $$('[data-app-page]').forEach((el) => el.addEventListener('click', () => setPage(el.dataset.appPage)));
  $('#finish-profile').addEventListener('click', () => { screen('setup'); state.step = state.completed.name ? 1 : 0; renderQuestion(false); });
  $('#profile-edit').addEventListener('submit', saveProfile);
  $$('.mode-switch [data-mode]').forEach((el) => el.addEventListener('click', () => {
    state.mode = el.dataset.mode;
    refreshHome();
    if (state.liveConversation) state.liveConversation.sendContextualUpdate('The user selected ' + state.mode + ' personality. Respond accordingly within your configured rules.');
    toast(state.mode === 'mentor' ? 'Mentor mode · calm and practical' : 'Friend mode · warm and playful');
  }));
  $('#talk-button').addEventListener('click', () => { if (state.voiceStatus.ownerSignedIn && state.voiceStatus.agentReady) void toggleLiveConversation(); else listen('home'); });
  $('#replay-reply').addEventListener('click', () => { if (state.liveConversation) return toast('End the live voice call before replaying audio.'); void speak(state.lastReply || 'Hey, I’m Mini. I’m right here. Tell me what’s on your mind.'); });
  $('#stop-speaking').addEventListener('click', () => { if (state.liveConversation) void toggleLiveConversation(); if (state.recognizer) state.recognizer.abort(); stopVoicePlayback(); text('#voice-state', 'Ready when you are.'); });
  $('#type-toggle').addEventListener('click', () => {
    const form = $('#type-form'); form.classList.toggle('hidden');
    text('#type-toggle span', form.classList.contains('hidden') ? 'Open text input ↓' : 'Close text input ↑');
    if (!form.classList.contains('hidden')) $('#type-input').focus();
  });
  $('#type-form').addEventListener('submit', (event) => { event.preventDefault(); const typed = $('#type-input').value.trim(); if (!typed) return; if (state.liveConversation) { state.liveConversation.sendUserMessage(typed); text('#user-transcript', typed); $('#type-input').value = ''; state.hasTalked = true; save(); refreshHome(); } else handleMessage(typed); });
  $('#toggle-captions').addEventListener('click', () => { state.captions = !state.captions; refreshHome(); });
  $('#show-captions').addEventListener('change', (event) => { state.captions = event.target.checked; refreshHome(); });
  $('#voice-output').addEventListener('change', (event) => {
    state.voiceOutput = event.target.checked;
    if (!state.voiceOutput) stopVoicePlayback();
  });
  $('#voice-signin').addEventListener('click', begin);
  $('#voice-logout').addEventListener('click', () => void logoutOwner());
  $('#voice-test').addEventListener('click', () => void speak('Hey, I’m Mini. This is what I sound like when we talk.'));
  $('#eleven-voice-list').addEventListener('change', (event) => { state.chosenVoiceId = event.target.value; try { localStorage.setItem('mini-ai-voice-preference', state.chosenVoiceId); } catch (_) {} toast('Voice selected for spoken replies.'); });
  $('#clear-local').addEventListener('click', resetData);
  $('#sidebar-reset').addEventListener('click', resetData);

  const hadProfile = load();
  if (hadProfile) {
    // Do not auto-assume a persisted browser profile means an authenticated identity.
    $('#header-start').textContent = 'Resume preview ↗';
    $('#header-start').addEventListener('click', () => toast('This is a local demo profile, not a signed-in account.'));
  }
  try { state.chosenVoiceId = localStorage.getItem('mini-ai-voice-preference') || ''; } catch (_) {}
  selectAuth('google');
  void refreshVoiceStatus();
  refreshProfilePreview();
  refreshHome();
})();
