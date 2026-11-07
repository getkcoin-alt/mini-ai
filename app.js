import { createVoiceRequestGate, voiceResponseError } from './voice-request-gate.js';
import { installMiniAccountUI } from './mini-identity-ui.js';

/* Mini AI — frontend-only interactive prototype.
 * Important: browser speech APIs and scripted demo responses are NOT an AI backend,
 * and the Google/email/WhatsApp flows below DO NOT authenticate real users.
 */
(function () {
  'use strict';

  const voiceGate = createVoiceRequestGate();
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
  const state = { profile: { ...defaults }, completed: {}, hasTalked: false, step: 0, auth: 'google', page: 'today', mode: 'friend', isListening: false, recognizer: null, autoSpeak: true, voiceOutput: true, captions: true, lastReply: '', previewGuest: true, demoExploration: false, voiceStatus: { authReady: false, ownerSignedIn: false, workerReady: false, referenceReady: false, voiceReady: false, localStandalone: false }, voiceAbort: null, voiceAudio: null, voiceAudioUrl: null, lastAudioBase64: '', recorder: null, recordingStream: null, recordingTimer: null, sendingVoice: false, suppressPendingVoice: false, discardNextRecording: false, supaUser: null };

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
    if (!state.recorder && !state.sendingVoice) text('#voice-helper', active ? 'Speak naturally. Tap the mic to stop.' : 'Tap to talk · Browser speech preview');
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
    if (announce && state.autoSpeak && !voiceGate.isBusy() && !state.sendingVoice) void speak(q.question, state.mode, { automatic: true });
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
    if (canUseWorker()) { void sendTextTurn(value); return; }
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


  // Independent, zero-shot Mini voice. No ElevenLabs API calls or models.
  const canUseWorker = () => Boolean(state.voiceStatus.voiceReady && state.voiceStatus.workerReady
    && (state.voiceStatus.localStandalone || state.voiceStatus.ownerSignedIn));

  function stopVoicePlayback() {
    // Cancel only playback. Aborting HTTP does NOT reliably stop server-side
    // model inference and can cause the next request to hit HTTP 429.
    if (state.voiceAudio) { try { state.voiceAudio.pause(); state.voiceAudio.src = ''; } catch (_) {} }
    state.voiceAudio = null;
    if (state.voiceAudioUrl) { URL.revokeObjectURL(state.voiceAudioUrl); state.voiceAudioUrl = null; }
    if ('speechSynthesis' in window) window.speechSynthesis.cancel();
    $('#app-orb')?.classList.remove('speaking');
  }

  async function voiceRequest(path, payload, method = 'POST') {
    const inferenceRequest = /^(speak|chat|turn|sample)(\?|$)/.test(path);
    const work = async () => {
      const controller = new AbortController();
      state.voiceAbort = controller;
      try {
        const res = await fetch('/api/voice/' + path, {
          method, credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          ...(payload === undefined ? {} : { body: JSON.stringify(payload) }),
          signal: controller.signal
        });
        const result = await res.json().catch(() => ({}));
        if (!res.ok) throw voiceResponseError(res.status, result);
        return result;
      } finally {
        if (state.voiceAbort === controller) state.voiceAbort = null;
      }
    };
    if (!inferenceRequest) return work();
    try {
      return await voiceGate.run(async () => {
        updateVoiceUi();
        return work();
      });
    } finally {
      // The gate has released by now; re-enable local controls.
      updateVoiceUi();
    }
  }

  async function toBase64(blob) {
    return await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(',')[1] || '');
      reader.onerror = () => reject(new Error('Could not read audio from this browser.'));
      reader.readAsDataURL(blob);
    });
  }

  async function playLocalAudio(base64) {
    if (!base64) throw new Error('Local model returned no voice recording.');
    stopVoicePlayback();
    const decoded = atob(base64);
    const bytes = new Uint8Array(decoded.length);
    for (let i = 0; i < decoded.length; i++) bytes[i] = decoded.charCodeAt(i);
    const url = URL.createObjectURL(new Blob([bytes], { type: 'audio/wav' }));
    state.voiceAudioUrl = url;
    const audio = new Audio(url);
    state.voiceAudio = audio;
    audio.onplay = () => { $('#app-orb')?.classList.add('speaking'); text('#voice-state', 'Mini is speaking in your chosen voice...'); };
    audio.onended = () => {
      $('#app-orb')?.classList.remove('speaking'); text('#voice-state', 'Ready when you are.');
      if (state.voiceAudioUrl === url) { URL.revokeObjectURL(url); state.voiceAudioUrl = null; }
    };
    audio.onerror = () => toast('Audio playback failed. Try again.');
    try { await audio.play(); }
    catch (_) { toast('Tap replay to hear the generated Mini voice.'); }
  }

  async function speak(message, mode = state.mode, { automatic = false } = {}) {
    if (!state.voiceOutput || !message) return false;
    if (canUseWorker()) {
      if (voiceGate.isBusy() || state.sendingVoice) {
        if (!automatic) toast('Mini is finishing another voice response. Please try again shortly.');
        return false;
      }
      state.suppressPendingVoice = false;
      try {
        stopVoicePlayback();
        text('#voice-state', 'Generating your local Mini voice...');
        const response = await voiceRequest('speak', { text: String(message).slice(0, 700), language: 'en', mode });
        state.lastAudioBase64 = response.audio_base64 || '';
        if (state.suppressPendingVoice) {
          text('#voice-state', 'Voice muted. You can replay it when ready.');
          return true;
        }
        await playLocalAudio(state.lastAudioBase64);
        return true;
      } catch (error) {
        if (error.name !== 'AbortError') toast('Local voice failed: ' + error.message);
        text('#voice-state', 'Local voice unavailable.');
        return false;
      }
    }
    return browserSpeak(message);
  }

  function applyVoiceReply(result) {
    text('#user-transcript', result.transcript || 'Voice recording');
    text('#mini-transcript', '“' + (result.reply || '') + '”');
    state.lastReply = result.reply || '';
    state.lastAudioBase64 = result.audio_base64 || '';
    state.hasTalked = true; save(); refreshHome();
    if (state.voiceOutput && result.audio_base64 && !state.suppressPendingVoice) void playLocalAudio(result.audio_base64);
    else text('#voice-state', state.suppressPendingVoice ? 'Reply ready · audio muted.' : 'Response ready.');
  }

  async function sendTextTurn(message) {
    if (!canUseWorker()) return handleMessage(message);
    if (state.sendingVoice || voiceGate.isBusy()) return toast('Mini is finishing a voice response. Try again when it is ready.');
    state.suppressPendingVoice = false;
    state.sendingVoice = true;
    stopVoicePlayback();
    text('#voice-state', 'Thinking and generating a voice...');
    text('#user-transcript', message);
    $('#type-input').value = '';
    try {
      const detected = /[\u0900-\u097F]/.test(message) ? 'hi' : 'en';
      const answer = await voiceRequest('chat', { text: message.slice(0, 700), language: detected, mode: state.mode });
      applyVoiceReply(answer);
    } catch (error) {
      if (error.name !== 'AbortError') toast('Local AI reply failed: ' + error.message);
    } finally { state.sendingVoice = false; updateVoiceUi(); }
  }

  async function toggleVoiceRecording() {
    if (state.recorder) {
      if (state.recorder.state === 'recording') state.recorder.stop();
      return;
    }
    if (!canUseWorker()) return listen('home');
    if (state.sendingVoice || voiceGate.isBusy()) return toast('Mini is still generating a response. Try again shortly.');
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) return toast('This browser cannot record voice. Try typing.');
    try {
      stopVoicePlayback();
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      const formats = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/webm', 'audio/ogg'];
      const chosen = formats.find(type => MediaRecorder.isTypeSupported(type)) || '';
      const recorder = chosen ? new MediaRecorder(stream, { mimeType: chosen }) : new MediaRecorder(stream);
      const chunks = [];
      state.recorder = recorder;
      state.recordingStream = stream;
      recorder.ondataavailable = event => { if (event.data?.size) chunks.push(event.data); };
      recorder.onstop = async () => {
        clearTimeout(state.recordingTimer); state.recordingTimer = null;
        stream.getTracks().forEach(track => track.stop());
        state.recordingStream = null;
        state.recorder = null;
        $('#talk-button').classList.remove('listening');
        text('#talk-icon', '🎙');
        if (state.discardNextRecording) {
          state.discardNextRecording = false;
          text('#voice-state', 'Recording discarded.');
          return;
        }
        const blob = new Blob(chunks, { type: recorder.mimeType || 'audio/webm' });
        if (blob.size < 1000) { toast('No audio was recorded. Try again.'); return; }
        if (blob.size > 3_000_000) { toast('Recording too large. Try a shorter message.'); return; }
        state.suppressPendingVoice = false;
        state.sendingVoice = true;
        text('#voice-state', 'Hearing, thinking, speaking...');
        try {
          const answer = await voiceRequest('turn', {
            audio_base64: await toBase64(blob),
            mime: (recorder.mimeType || blob.type || 'audio/webm').split(';')[0],
            mode: state.mode
          });
          applyVoiceReply(answer);
        } catch (error) {
          if (error.name !== 'AbortError') toast('Speech turn failed: ' + error.message);
          text('#voice-state', 'Could not finish this voice turn.');
        } finally { state.sendingVoice = false; updateVoiceUi(); }
      };
      recorder.start();
      $('#talk-button').classList.add('listening');
      text('#talk-icon', '■');
      text('#voice-state', 'Listening to your voice...');
      text('#voice-helper', 'Tap the square to send · Up to 12 seconds per turn');
      state.recordingTimer = setTimeout(() => { if (recorder.state === 'recording') recorder.stop(); }, 12000);
    } catch (error) { toast('Microphone permission required: ' + error.message); }
  }

  const canSyncProfile = () => Boolean(state.supaUser || (state.voiceStatus.workerReady &&
    (state.voiceStatus.ownerSignedIn || state.voiceStatus.localStandalone)));

  function updateMemoryUi() {
    const allowed = canSyncProfile();
    $('#memory-consent').disabled = !allowed;
    $('#memory-save').disabled = !allowed;
    $('#memory-forget').disabled = !allowed;
    if (!allowed) text('#memory-status', 'Private Mini AI memory is offline. Your setup stays only in this browser.');
  }

  async function readMemoryStatus() {
    if (state.supaUser) return;
    if (!canSyncProfile()) return updateMemoryUi();
    try {
      const res = await fetch('/api/voice/profile', { credentials: 'same-origin', cache: 'no-store' });
      if (!res.ok) throw new Error('Profile service unavailable');
      const data = await res.json();
      text('#memory-status', data.saved ? 'Profile saved on your private worker. Mini can use it in spoken replies.' : 'No server profile saved. You control when Mini remembers.');
    } catch (_) {
      text('#memory-status', 'Could not read private memory. Your browser preferences remain local.');
    }
  }

  async function syncPrivateProfile() {
    if (!canSyncProfile()) return toast('Connect your private Mini AI worker before saving memory.');
    if (!$('#memory-consent').checked) return toast('Confirm your permission before saving profile facts.');
    const profile = {};
    questions.forEach(q => { if (state.completed[q.key] && String(state.profile[q.key] || '').trim()) profile[q.key] = String(state.profile[q.key]).slice(0, q.key === 'focus' || q.key === 'boundaries' ? 600 : 80); });
    if (!Object.keys(profile).length) return toast('Answer at least one setup question first.');
    $('#memory-save').disabled = true;
    try {
      const res = await fetch('/api/voice/profile', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ profile, consent: true })
      });
      const result = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(result.error || result.detail || 'Profile save failed');
      $('#memory-consent').checked = false;
      await readMemoryStatus();
      toast('Mini saved only the setup facts you selected.');
    } catch (error) { toast('Memory sync failed: ' + error.message); }
    finally { updateMemoryUi(); }
  }

  async function forgetPrivateProfile() {
    if (!canSyncProfile()) return;
    if (!confirm('Delete the profile saved on your private Mini server? Your local browser profile will remain.')) return;
    $('#memory-forget').disabled = true;
    try {
      const res = await fetch('/api/voice/profile', { method: 'DELETE', credentials: 'same-origin' });
      const result = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(result.error || result.detail || 'Delete failed');
      await readMemoryStatus();
      toast('Mini has deleted its private server profile.');
    } catch (error) { toast('Could not delete server profile: ' + error.message); }
    finally { updateMemoryUi(); }
  }

  function updateVoiceUi() {
    const v = state.voiceStatus;
    const ownerAccess = Boolean(v.ownerSignedIn || v.localStandalone);
    const status = canUseWorker()
      ? 'FREE LOCAL SPEECH · CHATTERBOX + WHISPER + OLLAMA'
      : v.workerReady ? 'VOICE WORKER READY · ADD A REFERENCE RECORDING'
      : 'BROWSER DEMO · LOCAL MODEL NOT CONNECTED';
    text('#voice-engine-status', status);
    text('#conversation-source-note', canUseWorker() ? '✳ Local Mini AI voice active: Whisper + Ollama + Chatterbox. This is turn-based, not continuous streaming.' : '✳ Browser demo uses scripted replies. Connect your local AI worker and voice reference for real speech turns.');
    text('#voice-account-status', v.localStandalone ? 'Private local worker is running on this computer.'
      : !v.authReady ? 'To use this from Vercel, deploy a private voice worker and configure Google owner authentication.'
      : !v.ownerSignedIn ? 'Sign in to access your private voice worker.'
      : !v.workerReady ? 'Owner signed in. Private voice worker is not reachable.'
      : 'Private voice worker is connected.');
    const modes = v.referenceModes || {};
    text('#voice-sample-status', 'Best Friend voice: ' + (modes.friend ? 'installed' : 'not installed') + ' · Mentor voice: ' + (modes.mentor ? 'installed' : 'not installed') + '. Upload a recording for each style.');
    text('#voice-engine-note', v.workerReady
      ? 'Audio generation runs through the private Chatterbox model, with faster-whisper and local Ollama for complete speech turns. No ElevenLabs API used.'
      : 'Run the Python worker on your computer, or link a securely hosted GPU worker. Mini does not download or export ElevenLabs voice weights.');
    show('#voice-signin', !v.localStandalone && v.authReady && !v.ownerSignedIn);
    show('#voice-logout', !v.localStandalone && v.ownerSignedIn);
    $('#voice-reference-file').disabled = !(v.workerReady && ownerAccess);
    $('#voice-rights').disabled = !(v.workerReady && ownerAccess);
    $('#voice-upload').disabled = !(v.workerReady && ownerAccess);
    $('#voice-test').disabled = !canUseWorker() || voiceGate.isBusy() || state.sendingVoice;
    $('#voice-delete').disabled = !(v.workerReady && ownerAccess && Boolean((v.referenceModes || {})[$('#voice-style').value]));
    updateMemoryUi();
    if (!state.recorder && !state.sendingVoice) {
      text('#voice-helper', canUseWorker()
        ? 'Tap to record · Private Whisper → Ollama → your Chatterbox voice'
        : 'Tap to talk · Browser speech preview until local AI is connected.');
    }
  }

  async function refreshVoiceStatus() {
    try {
      const res = await fetch('/api/voice/status', { credentials: 'same-origin', cache: 'no-store' });
      if (!res.ok) throw new Error('Worker status unavailable');
      const data = await res.json();
      state.voiceStatus = {
        authReady: Boolean(data.authReady),
        ownerSignedIn: Boolean(data.ownerSignedIn),
        workerReady: Boolean(data.workerReady),
        referenceReady: Boolean(data.referenceReady),
        referenceModes: data.referenceModes && typeof data.referenceModes === 'object' ? data.referenceModes : {},
        localStandalone: Boolean(data.localStandalone),
        voiceReady: Boolean(data.voiceReady ?? (data.workerReady && data.referenceReady))
      };
      updateVoiceUi();
      if (canSyncProfile()) void readMemoryStatus();
      if (state.voiceStatus.authReady && data.googleClientId) initGoogleButton(data.googleClientId);
    } catch (_) {
      state.voiceStatus = { authReady: false, ownerSignedIn: false, workerReady: false, referenceReady: false, localStandalone: false, voiceReady: false };
      updateVoiceUi();
    }
  }

  let googleButtonInitialized = false;
  function initGoogleButton(clientId) {
    if (googleButtonInitialized || !clientId) return;
    googleButtonInitialized = true;
    const script = document.createElement('script');
    script.src = 'https://accounts.google.com/gsi/client';
    script.async = true; script.defer = true;
    script.onload = () => {
      try {
        if (!window.google?.accounts?.id) throw new Error('Google client unavailable');
        window.google.accounts.id.initialize({
          client_id: clientId,
          callback: async ({ credential }) => {
            if (!credential) return;
            try {
              const response = await fetch('/api/auth/google', {
                method: 'POST', credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ credential })
              });
              const result = await response.json();
              if (!response.ok) throw new Error(result.error || 'Sign-in failed');
              await refreshVoiceStatus();
              toast('Signed in. You can now use your own secure voice worker if it is configured.');
              if (Object.values(state.completed).some(Boolean)) enterHome();
              else startSetup();
            } catch (error) { toast('Google sign-in failed: ' + String(error.message).slice(0, 160)); }
          }
        });
        const slot = $('#google-real-slot');
        slot.replaceChildren();
        window.google.accounts.id.renderButton(slot, { type: 'standard', theme: 'filled_black', size: 'large', text: 'continue_with', shape: 'pill', width: 320 });
        show('#google-real-slot', true);
        show('#google-signin', false);
        text('#google-auth-hint', 'Google sign-in protects your self-hosted voice service on Vercel. It does not access your ElevenLabs account.');
      } catch (_) { toast('Google sign-in could not load. Check OAuth origins.'); }
    };
    script.onerror = () => toast('Google sign-in scripts are blocked in this browser.');
    document.head.append(script);
  }

  async function uploadVoiceReference() {
    const file = $('#voice-reference-file').files?.[0];
    if (!file) return toast('Choose a voice recording first.');
    if (!$('#voice-rights').checked) return toast('Confirm that you own the voice or have explicit permission to use it.');
    if (file.size > 3_000_000) return toast('Reference must be 3 MB or less.');
    if (!state.voiceStatus.workerReady) return toast('Start your local voice worker first.');
    $('#voice-upload').disabled = true;
    text('#voice-sample-status', 'Preparing your private voice reference...');
    try {
      const result = await voiceRequest('sample', { audio_base64: await toBase64(file), mime: file.type || 'application/octet-stream', consent: true, mode: $('#voice-style').value });
      toast('Reference saved on your private worker (' + result.durationSeconds + ' seconds).');
      $('#voice-rights').checked = false;
      $('#voice-reference-file').value = '';
      await refreshVoiceStatus();
    } catch (error) {
      if (error.name !== 'AbortError') toast('Reference upload failed: ' + error.message);
      updateVoiceUi();
    } finally { $('#voice-upload').disabled = !state.voiceStatus.workerReady; }
  }

  async function removeVoiceReference() {
    if (!confirm('Delete Mini’s private reference recording from the worker? This cannot be undone.')) return;
    try {
      await voiceRequest('sample?mode=' + encodeURIComponent($('#voice-style').value), undefined, 'DELETE');
      state.lastAudioBase64 = '';
      await refreshVoiceStatus();
      toast('Reference recording for ' + $('#voice-style').value + ' removed from the private worker.');
    } catch (error) { toast('Delete failed: ' + error.message); }
  }

  async function logoutOwner() {
    try { await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' }); } catch (_) {}
    if (state.recorder?.state === 'recording') state.recorder.stop();
    stopVoicePlayback();
    await refreshVoiceStatus();
    toast('Signed out from your private owner session.');
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
     toast(state.mode === 'mentor' ? 'Mentor mode · calm and practical' : 'Friend mode · warm and playful');
  }));
  $('#talk-button').addEventListener('click', () => { if (state.recorder || canUseWorker()) void toggleVoiceRecording(); else listen('home'); });
  $('#replay-reply').addEventListener('click', () => { if (state.lastAudioBase64 && canUseWorker()) void playLocalAudio(state.lastAudioBase64); else void speak(state.lastReply || 'Hey, I’m Mini. I’m right here. Tell me what’s on your mind.'); });
  $('#stop-speaking').addEventListener('click', () => {
    if (state.recorder) {
      state.discardNextRecording = true;
      state.recorder.stop();
    }
    if (state.recognizer) state.recognizer.abort();
    if (voiceGate.isBusy()) state.suppressPendingVoice = true;
    stopVoicePlayback();
    text('#voice-state', voiceGate.isBusy() ? 'Mini is still processing; its response will be muted.' : 'Ready when you are.');
  });
  $('#type-toggle').addEventListener('click', () => {
    const form = $('#type-form'); form.classList.toggle('hidden');
    text('#type-toggle span', form.classList.contains('hidden') ? 'Open text input ↓' : 'Close text input ↑');
    if (!form.classList.contains('hidden')) $('#type-input').focus();
  });
  $('#type-form').addEventListener('submit', (event) => { event.preventDefault(); handleMessage($('#type-input').value); });
  $('#toggle-captions').addEventListener('click', () => { state.captions = !state.captions; refreshHome(); });
  $('#show-captions').addEventListener('change', (event) => { state.captions = event.target.checked; refreshHome(); });
  $('#voice-output').addEventListener('change', (event) => {
    state.voiceOutput = event.target.checked;
    if (!state.voiceOutput) stopVoicePlayback();
  });
  $('#voice-signin').addEventListener('click', begin);
  $('#voice-logout').addEventListener('click', () => void logoutOwner());
  $('#voice-test').addEventListener('click', () => void speak('Hey, I am Mini. This is the voice you chose for me. How does it sound?', $('#voice-style').value));
  $('#voice-upload').addEventListener('click', () => void uploadVoiceReference());
  $('#voice-style').addEventListener('change', () => updateVoiceUi());
  $('#voice-delete').addEventListener('click', () => void removeVoiceReference());
  $('#memory-save').addEventListener('click', () => void syncPrivateProfile());
  $('#memory-forget').addEventListener('click', () => void forgetPrivateProfile());
  $('#clear-local').addEventListener('click', resetData);
  $('#sidebar-reset').addEventListener('click', resetData);

  const hadProfile = load();
  if (hadProfile) {
    // Do not auto-assume a persisted browser profile means an authenticated identity.
    $('#header-start').textContent = 'Resume preview ↗';
    $('#header-start').addEventListener('click', () => toast('This is a local demo profile, not a signed-in account.'));
  }
   selectAuth('google');
  void installMiniAccountUI({
    onVerified: () => startSetup(),
    onState: (user) => {
      // A different verified account must never inherit a previous demo user's
      // local answers, including after a Google redirect or a shared computer.
      if (user?.id && user.id !== state.supaUser?.id) {
        try { localStorage.removeItem(STORAGE_KEY); } catch (_) {}
        state.profile = { ...defaults };
        state.completed = {};
        state.hasTalked = false;
        state.lastReply = '';
        refreshProfilePreview();
        refreshHome();
      }
      state.supaUser = user;
      updateMemoryUi();
    },
    getProfile: () => ({ profile: state.profile, completed: state.completed }),
    onProfileLoaded: (record) => {
      const saved = {
        name: record.display_name, miniName: record.mini_name,
        relationship: record.companion_mode, tone: record.tone,
        focus: record.focus, boundaries: record.boundaries
      };
      state.profile = { ...defaults };
      state.completed = {};
      const answered = new Set(Array.isArray(record.completed_keys) ? record.completed_keys : []);
      for (const key of Object.keys(defaults)) {
        if (typeof saved[key] === 'string' && saved[key].trim()) {
          state.profile[key] = saved[key];
          if (answered.has(key)) state.completed[key] = true;
        }
      }
      refreshProfilePreview();
      refreshHome();
    },
    onSignOut: async () => {
      // Sign out the legacy owner-only cookie as well if present.
      try { await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' }); } catch (_) {}
      try { localStorage.removeItem(STORAGE_KEY); } catch (_) {}
      state.profile = { ...defaults }; state.completed = {}; state.hasTalked = false;
      screen('welcome');
    },
    notify: toast
  }).catch(error => toast('Account connection unavailable: ' + String(error.message).slice(0,100)));
  void refreshVoiceStatus();
  refreshProfilePreview();
  refreshHome();
})();
