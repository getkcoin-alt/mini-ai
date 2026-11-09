-- Mini is for adults (18+). The user confirms this once; the Vercel gateway
-- checks it (with the user's own token, so RLS applies) before issuing a
-- live-voice ticket when MINI_REQUIRE_AGE_CONFIRMATION=true.
ALTER TABLE public.mini_profiles
  ADD COLUMN IF NOT EXISTS age_confirmed_at timestamptz;
