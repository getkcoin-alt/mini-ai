import { createClient } from '@supabase/supabase-js';
import { MINI_REALTIME_PROTOCOL, MINI_WS_PATH } from '../../mini-realtime-protocol.js';

function noStore(res) {
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('X-Content-Type-Options', 'nosniff');
}

/**
 * Fail-closed readiness gate for the future authenticated Mini WSS gateway.
 * This endpoint does NOT proxy voice or create a websocket. Never set READY
 * until a separate WSS route validates session.start against Supabase.
 */
export default async function handler(req, res) {
  noStore(res);
  if (req.method !== 'GET') {
    res.setHeader('Allow','GET');
    return res.status(405).json({enabled:false});
  }
  const token = /^Bearer (.{20,6000})$/.exec(String(req.headers?.authorization||''))?.[1];
  if (!token) return res.status(401).json({enabled:false,error:'Sign in to Mini first.'});
  const url = process.env.MINI_SUPABASE_URL || '';
  const key = process.env.MINI_SUPABASE_PUBLISHABLE_KEY || '';
  if (!/^https:\/\/[a-z0-9-]+\.supabase\.co$/.test(url) || !/^sb_publishable_/.test(key))
    return res.status(503).json({enabled:false,reason:'auth_unconfigured'});
  try {
    // No service-role secret: this validates the real signed-in user remotely.
    const supabase = createClient(url,key,{
      auth:{persistSession:false,autoRefreshToken:false,detectSessionInUrl:false}
    });
    const {data,error}=await supabase.auth.getUser(token);
    if (error || !data?.user?.id)
      return res.status(401).json({enabled:false,error:'Sign in to Mini again.'});
    const ready = process.env.MINI_REALTIME_ENABLED === 'true'
      && process.env.MINI_REALTIME_GATEWAY_READY === 'true';
    return res.status(200).json({
      enabled:ready, protocol:MINI_REALTIME_PROTOCOL,
      wsPath:MINI_WS_PATH,
      input:{format:'pcm16',sampleRate:16000,frameMs:20},
      output:{format:'pcm16',sampleRate:24000},
      ...(ready ? {} : {reason:'nfc_gateway_not_ready'})
    });
  } catch {
    return res.status(503).json({enabled:false,reason:'identity_unavailable'});
  }
}
