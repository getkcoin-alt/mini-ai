import { createClient } from '@supabase/supabase-js';

// Identity is always resolved from Supabase Auth; never trust browser-supplied user IDs.
// Public configuration consists ONLY of project URL and publishable key.
// The service role / worker master token must NEVER be included here.
let client = null;
let whatsappReady = false;

export async function configureMiniIdentity() {
  if (client) return { enabled: true, whatsappReady };
  const response = await fetch('/api/auth/public-config', { cache: 'no-store', credentials: 'same-origin' });
  if (!response.ok) return { enabled: false, whatsappReady: false };
  const config = await response.json();
  if (config.enabled !== true || !/^https:\/\/[a-z0-9-]+\.supabase\.co$/.test(config.url || '') ||
      !/^sb_publishable_/.test(config.publishableKey || '')) {
    return { enabled: false, whatsappReady: false };
  }
  client = createClient(config.url, config.publishableKey, {
    auth: { autoRefreshToken: true, persistSession: true, detectSessionInUrl: true,
      flowType: 'pkce', storageKey: 'mini-auth-v1' }
  });
  whatsappReady = config.whatsappReady === true;
  return { enabled: true, whatsappReady };
}

export function miniIdentity() { return client; }
export function miniWhatsAppReady() { return whatsappReady; }

export async function currentMiniUser() {
  if (!client) return null;
  const { data, error } = await client.auth.getUser();
  if (error) return null;
  return data?.user || null;
}

export async function googleMiniLogin() {
  if (!client) throw new Error('Mini authentication has not been configured.');
  const { error } = await client.auth.signInWithOAuth({
    provider: 'google',
    options: { redirectTo: window.location.origin + window.location.pathname }
  });
  if (error) throw error;
}

export async function sendEmailMiniOtp(email) {
  if (!client) throw new Error('Mini authentication is unavailable.');
  const normalized = String(email || '').trim().toLowerCase();
  if (normalized.length > 254 || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(normalized))
    throw new Error('Enter a valid email address.');
  const { error } = await client.auth.signInWithOtp({
    email: normalized, options: { shouldCreateUser: true, emailRedirectTo: window.location.origin }
  });
  if (error) throw error;
}

export async function verifyEmailMiniOtp(email, token) {
  if (!client) throw new Error('Mini authentication is unavailable.');
  if (!/^\d{6,8}$/.test(String(token).trim())) throw new Error('Enter the code sent to your email.');
  const { data, error } = await client.auth.verifyOtp({
    email: String(email).trim().toLowerCase(), token: String(token).trim(), type: 'email'
  });
  if (error || !data?.user) throw error || new Error('Email verification failed.');
  return data.user;
}

export async function sendWhatsAppMiniOtp(phoneE164) {
  if (!client || !whatsappReady) throw new Error('Scriwo WhatsApp delivery has not been verified yet.');
  if (!/^\+[1-9]\d{7,14}$/.test(phoneE164)) throw new Error('Provide a valid international phone number.');
  // Supabase's Send SMS Hook must deliver this OTP through the verified Scriwo API.
  // Do not select channel='whatsapp': that provider-specific path is not the custom SMS hook.
  const { error } = await client.auth.signInWithOtp({ phone: phoneE164 });
  if (error) throw error;
}

export async function verifyWhatsAppMiniOtp(phoneE164, token) {
  if (!client || !whatsappReady) throw new Error('WhatsApp verification is not enabled.');
  if (!/^\+[1-9]\d{7,14}$/.test(phoneE164) || !/^\d{6,8}$/.test(String(token).trim()))
    throw new Error('Enter a valid phone number and verification code.');
  const { data, error } = await client.auth.verifyOtp({
    phone: phoneE164, token: String(token).trim(), type: 'sms'
  });
  if (error || !data?.user) throw error || new Error('Phone verification failed.');
  return data.user;
}

export async function signOutMini() {
  if (!client) return;
  const { error } = await client.auth.signOut({ scope: 'local' });
  if (error) throw error;
}

function validateProfile(input) {
  const valid = {
    name: 80, miniName: 80, relationship: 20, tone: 20, focus: 600, boundaries: 600, birthYear: 4
  };
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error('Invalid profile.');
  const out = {};
  for (const [key, limit] of Object.entries(valid)) {
    const value = input[key];
    if (value === undefined || value === null) continue;
    if (typeof value !== 'string' || value.length > limit) throw new Error('Invalid ' + key + '.');
    out[key] = value.trim();
  }
  return out;
}
export function profileRowForUser(userId, profile, now = new Date().toISOString()) {
  if (!/^[a-f\d-]{36}$/i.test(userId)) throw new Error('Invalid identity.');
  const data = validateProfile(profile);
  if (!['friend', 'mentor', 'both', undefined].includes(data.relationship)) throw new Error('Invalid companion mode.');
  if (!['gentle', 'balanced', 'direct', undefined].includes(data.tone)) throw new Error('Invalid tone.');
  if (data.birthYear !== undefined && data.birthYear !== '' && !/^(19[2-9]\d|20[0-3]\d)$/.test(data.birthYear))
    throw new Error('Invalid birth year.');
  return { user_id: userId, display_name: data.name || '',
    mini_name: data.miniName || 'Mini', companion_mode: data.relationship || 'both',
    tone: data.tone || 'balanced', focus: data.focus || '',
    boundaries: data.boundaries || '',
    ...(data.birthYear ? { birth_year: Number(data.birthYear) } : {}),
    ...(data.birthYear && new Date(now).getUTCFullYear() - Number(data.birthYear) >= 18 ? { age_confirmed_at: now } : {}),
    completed_keys: Object.keys(data).filter(key => key !== 'birthYear' && data[key].length > 0),
    consented_at: now, updated_at: now };
}

export async function readMiniProfile() {
  if (!client) throw new Error('Authentication unavailable.');
  const user = await currentMiniUser();
  if (!user) throw new Error('Sign in first.');
  const { data, error } = await client.from('mini_profiles').select(
    'display_name,mini_name,companion_mode,tone,focus,boundaries,completed_keys,birth_year,updated_at'
  ).eq('user_id', user.id).maybeSingle();
  if (error) throw error;
  return data || null;
}

export async function saveMiniProfile(profile, consent) {
  if (consent !== true) throw new Error('Choose to remember your profile first.');
  if (!client) throw new Error('Authentication unavailable.');
  const user = await currentMiniUser();
  if (!user) throw new Error('Sign in first.');
  const row = profileRowForUser(user.id, profile);
  const { error } = await client.from('mini_profiles').upsert(row, { onConflict: 'user_id' });
  if (error) throw error;
  return row;
}

export async function forgetMiniProfile() {
  if (!client) throw new Error('Authentication unavailable.');
  const user = await currentMiniUser();
  if (!user) throw new Error('Sign in first.');
  const { error } = await client.from('mini_profiles').delete().eq('user_id', user.id);
  if (error) throw error;
}

export async function listMiniMemories() {
  if (!client) throw new Error('Authentication unavailable.');
  const user = await currentMiniUser();
  if (!user) throw new Error('Sign in first.');
  const { data, error } = await client.from('mini_memories')
    .select('id,kind,content,confirmed_at,expires_at')
    .eq('user_id', user.id).order('created_at', { ascending: false }).limit(40);
  if (error) throw error;
  return data || [];
}

export async function rememberMiniFact({ kind, content, consent }) {
  if (consent !== true) throw new Error('Confirm this memory first.');
  if (!client) throw new Error('Authentication unavailable.');
  const user = await currentMiniUser();
  if (!user) throw new Error('Sign in first.');
  if (!['preference','goal','project','fact'].includes(kind) ||
      typeof content !== 'string' || content.trim().length < 1 || content.length > 1600)
    throw new Error('Choose a valid short memory.');
  const { error } = await client.from('mini_memories').insert({
    user_id: user.id, kind, content: content.trim(), confirmed_at: new Date().toISOString()
  });
  if (error) throw error;
}

export async function forgetMiniFact(id) {
  if (!client) throw new Error('Authentication unavailable.');
  const user = await currentMiniUser();
  if (!user) throw new Error('Sign in first.');
  if (!/^[a-f\d-]{36}$/i.test(id)) throw new Error('Invalid memory ID.');
  const { error } = await client.from('mini_memories').delete().eq('id', id).eq('user_id', user.id);
  if (error) throw error;
}

/** Permanently delete the signed-in account and everything Mini stored about it. */
export async function deleteMiniAccount() {
  if (!client) throw new Error('Authentication unavailable.');
  const { error } = await client.rpc('mini_delete_my_account');
  if (error) throw error;
  await client.auth.signOut({ scope: 'local' });
}
