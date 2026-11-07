import {
  configureMiniIdentity, miniIdentity, currentMiniUser, googleMiniLogin,
  sendEmailMiniOtp, verifyEmailMiniOtp, sendWhatsAppMiniOtp, verifyWhatsAppMiniOtp,
  signOutMini, readMiniProfile, saveMiniProfile, forgetMiniProfile,
  listMiniMemories, rememberMiniFact, forgetMiniFact
} from './mini-supabase.js';

// Auth UI adapter. A verified account never accepts a hard-coded demo verification code.
// Capture listeners intercept the legacy demo handlers without rewriting the
// existing voice/animation/onboarding modules.
export function installMiniAccountUI({ onVerified, onState, getProfile, onProfileLoaded, onSignOut, notify }) {
  let enabled = false;
  let whatsAppEnabled = false;
  let user = null;
  const $ = selector => document.querySelector(selector);
  const feedback = message => notify(String(message).slice(0, 180));
  const intercept = (node, event, fn) => node?.addEventListener(event, (e) => {
    const isAuth = ['google-signin', 'auth-email', 'auth-whatsapp'].includes(node?.id);
    if (!enabled && !isAuth) return; // Preserve existing private owner-pilot controls.
    if (enabled && !user && !isAuth) return; // Owner worker remains independent.
    e.preventDefault();
    e.stopImmediatePropagation();
    if (!enabled) return feedback('Real signup is not configured. Choose the separate demo option.');
    void Promise.resolve(fn(e)).catch(error => feedback(error.message || 'Unable to verify your account.'));
  }, { capture: true });

  async function reloadAccount() {
    user = await currentMiniUser();
    onState(user);
    const readout = $('#memory-status');
    if (user && readout) {
      try {
        const value = await readMiniProfile();
        readout.textContent = value ? 'Your private account profile is saved.' : 'No private account profile saved yet.';
        if (value && typeof onProfileLoaded === 'function') onProfileLoaded(value);
      } catch { readout.textContent = 'Could not load private profile.'; }
    }
  }

  intercept($('#google-signin'), 'click', () => googleMiniLogin());
  intercept($('#auth-email'), 'submit', async () => {
    const address = $('#email-address').value.trim();
    const wrap = $('#email-code-wrap');
    if (wrap.classList.contains('hidden')) {
      await sendEmailMiniOtp(address);
      wrap.classList.remove('hidden');
      $('#email-action').textContent = 'Verify email code ↗';
      feedback('Check your inbox for the actual verification code.');
    } else {
      const verified = await verifyEmailMiniOtp(address, $('#email-code').value);
      user = verified; onState(user); onVerified(user);
    }
  });
  intercept($('#auth-whatsapp'), 'submit', async () => {
    if (!whatsAppEnabled) return feedback('Scriwo WhatsApp OTP is not yet verified. No code was sent.');
    const input = $('#wa-phone').value.trim();
    const digits = input.replace(/\D/g, '');
    const phone = input.startsWith('+') ? '+' + digits : '+91' + digits;
    const wrap = $('#wa-code-wrap');
    if (wrap.classList.contains('hidden')) {
      await sendWhatsAppMiniOtp(phone);
      wrap.classList.remove('hidden');
      $('#wa-action').textContent = 'Verify WhatsApp code ↗';
      feedback('Check WhatsApp for the real code.');
    } else {
      const verified = await verifyWhatsAppMiniOtp(phone, $('#wa-code').value);
      user = verified; onState(user); onVerified(user);
    }
  });

  intercept($('#memory-save'), 'click', async () => {
    if (!user) return feedback('Sign into your account first.');
    if (!$('#memory-consent').checked) return feedback('Select permission to save your profile.');
    const { profile, completed } = getProfile();
    const fields = {};
    for (const [key, value] of Object.entries(profile)) {
      if (completed[key] === true) fields[key] = value;
    }
    await saveMiniProfile(fields, true);
    $('#memory-consent').checked = false;
    await reloadAccount();
    feedback('Your private profile was saved under your verified account.');
  });

  intercept($('#memory-forget'), 'click', async () => {
    if (!user) return feedback('Sign in first.');
    if (!confirm('Delete your saved account profile? This does not delete other memories or conversation history.')) return;
    await forgetMiniProfile();
    await reloadAccount();
    feedback('Your saved account profile was deleted.');
  });

  intercept($('#voice-logout'), 'click', async () => {
    await signOutMini();
    user = null; onState(null);
    await onSignOut();
    feedback('Signed out from your Mini AI account.');
  });

  // Personal memories require explicit, per-fact consent, and use the same RLS rules.
  // We add these controls to the existing memory screen without touching its look.
  const memoryPage = $('#memory-save')?.closest('.settings-panel');
  if (memoryPage) {
    const section = document.createElement('section');
    section.className = 'mini-private-memories';
    section.innerHTML = '<h3>Things you asked Mini to remember</h3>' +
      '<label for="mini-memory-text">New memory</label>' +
      '<textarea id="mini-memory-text" rows="2" maxlength="1600" placeholder="A goal, preference or important project"></textarea>' +
      '<label for="mini-memory-consent"><input type="checkbox" id="mini-memory-consent"> I want Mini to remember this specific fact.</label>' +
      '<div class="voice-action-row"><button class="button button-soft" type="button" id="mini-memory-add">Remember fact</button>' +
      '<button class="button button-outline" type="button" id="mini-memory-refresh">Refresh memories</button></div>' +
      '<div id="mini-memory-list" aria-live="polite"></div>';
    memoryPage.append(section);
    const renderMemories = async () => {
      const target = $('#mini-memory-list');
      target.replaceChildren();
      if (!user) { target.textContent = 'Sign into Mini to see your private memories.'; return; }
      const records = await listMiniMemories();
      if (!records.length) { target.textContent = 'No confirmed facts saved yet.'; return; }
      for (const item of records) {
        const row = document.createElement('div');
        row.className = 'mini-memory-row';
        const content = document.createElement('p');
        content.textContent = item.content;
        const remove = document.createElement('button');
        remove.type = 'button'; remove.className = 'button button-ghost button-small';
        remove.textContent = 'Forget';
        remove.addEventListener('click', async () => {
          try { await forgetMiniFact(item.id); await renderMemories(); }
          catch(error) { feedback(error.message); }
        });
        row.append(content, remove); target.append(row);
      }
    };
    $('#mini-memory-refresh').addEventListener('click', () => {
      void renderMemories().catch(error => feedback(error.message));
    });
    $('#mini-memory-add').addEventListener('click', () => {
      void (async () => {
        if (!$('#mini-memory-consent').checked) return feedback('Confirm that Mini may remember this fact.');
        await rememberMiniFact({ kind: 'fact', content: $('#mini-memory-text').value, consent: true });
        $('#mini-memory-text').value = '';
        $('#mini-memory-consent').checked = false;
        await renderMemories();
        feedback('Memory saved for your account.');
      })().catch(error => feedback(error.message));
    });
  }

  return (async () => {
    const config = await configureMiniIdentity();
    enabled = config.enabled;
    whatsAppEnabled = config.whatsappReady;
    if (!enabled) {
      $('#google-auth-hint').textContent = 'Real account signup is not configured here. Demo exploration remains available.';
      $('#email-action').textContent = 'Email verification unavailable';
      $('#email-action').disabled = true;
      $('#wa-action').textContent = 'WhatsApp verification unavailable';
      $('#wa-action').disabled = true;
      return { enabled: false };
    }
    $('#google-auth-hint').textContent = 'Real Google sign-in with Mini AI Auth.';
    $('#google-real-slot')?.classList.add('hidden');
    $('#google-signin')?.classList.remove('hidden');
    $('#email-action').textContent = 'Send real email code ↗';
    $('#wa-action').textContent = whatsAppEnabled ? 'Send WhatsApp code ↗' : 'Scriwo WhatsApp verification coming soon';
    $('#wa-action').disabled = !whatsAppEnabled;
    for (const el of document.querySelectorAll('.demo-code-hint')) el.remove();
    const client = miniIdentity();
    client.auth.onAuthStateChange((_name, session) => {
      user = session?.user || null;
      onState(user);
    });
    await reloadAccount();
    return { enabled: true, whatsappReady: whatsAppEnabled };
  })();
}
