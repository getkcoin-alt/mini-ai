// This endpoint exposes only the project's public URL and publishable key.
// The worker token and all Supabase service-role/secret keys remain server-side.
export default function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('X-Content-Type-Options','nosniff');
  if (req.method !== 'GET') {
    res.setHeader('Allow','GET');
    return res.status(405).json({ enabled:false });
  }
  const url = process.env.MINI_SUPABASE_URL || '';
  const publishableKey = process.env.MINI_SUPABASE_PUBLISHABLE_KEY || '';
  const configured = /^https:\/\/[a-z0-9-]+\.supabase\.co$/.test(url)
    && /^sb_publishable_[a-zA-Z0-9_-]+$/.test(publishableKey);
  if (!configured) return res.status(200).json({ enabled:false, whatsappReady:false });
  return res.status(200).json({
    enabled:true, url, publishableKey,
    whatsappReady: process.env.MINI_SCRIWO_OTP_VERIFIED === 'true'
  });
}
