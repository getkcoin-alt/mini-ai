-- Trigger functions are internal: never callable through the API.
REVOKE EXECUTE ON FUNCTION public.mind_audit() FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.mind_sync_from_profile() FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.mind_version_fact() FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.mind_facts_guard() FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.mind_compartment_guard() FROM PUBLIC, anon, authenticated;
-- Bring profiles created before the mind existed into it (fires mind_sync_from_profile).
UPDATE public.mini_profiles SET display_name = display_name;
