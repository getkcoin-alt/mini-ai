-- Age group for every user (Mini serves 8–100; adults first, children later
-- with verified parental consent). Only the birth year is stored.
ALTER TABLE public.mini_profiles
  ADD COLUMN IF NOT EXISTS birth_year smallint
  CHECK (birth_year IS NULL OR birth_year BETWEEN 1920 AND 2030);

-- Self-service "delete my account": removes the signed-in user from
-- auth.users; profiles, memories, conversations and messages cascade.
CREATE OR REPLACE FUNCTION public.mini_delete_my_account()
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
  IF auth.uid() IS NULL THEN
    RAISE EXCEPTION 'Not signed in';
  END IF;
  DELETE FROM auth.users WHERE id = auth.uid();
END;
$$;
REVOKE ALL ON FUNCTION public.mini_delete_my_account() FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.mini_delete_my_account() TO authenticated;
