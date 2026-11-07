-- Already applied to Miniai Supabase project (2026-11-07).
-- Mini's "sync percentage" must count genuinely answered questions, not SQL defaults.
ALTER TABLE public.mini_profiles
  ADD COLUMN IF NOT EXISTS completed_keys text[] NOT NULL DEFAULT '{}'::text[];
ALTER TABLE public.mini_profiles
  ADD CONSTRAINT mini_profiles_completed_keys_allowed
  CHECK (completed_keys <@ ARRAY['name','miniName','relationship','tone','focus','boundaries']::text[]);
