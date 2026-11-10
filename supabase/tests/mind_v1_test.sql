-- Mind v1 database tests: run by scripts/mind/run_db_tests.sh on a throwaway cluster.
-- Pilot: two adults (Arjun, a man aged 31 → stage 4; Meera, a woman aged 52 → stage 6),
-- plus a 15-year-old to prove children are never profiled.
\set ON_ERROR_STOP on

CREATE OR REPLACE FUNCTION pg_temp.as_user(u uuid) RETURNS void LANGUAGE plpgsql AS $$
BEGIN PERFORM set_config('request.jwt.claim.sub', u::text, false); EXECUTE 'SET ROLE authenticated'; END $$;
CREATE OR REPLACE FUNCTION pg_temp.expect_error(sql text, needle text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
  BEGIN EXECUTE sql;
  EXCEPTION WHEN others THEN
    IF position(lower(needle) IN lower(SQLERRM)) = 0 THEN RAISE EXCEPTION 'expected error "%" but got "%"', needle, SQLERRM; END IF;
    RETURN;
  END;
  RAISE EXCEPTION 'expected an error containing "%" for: %', needle, sql;
END $$;
CREATE OR REPLACE FUNCTION pg_temp.ok(cond boolean, what text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN IF cond IS NOT TRUE THEN RAISE EXCEPTION 'FAILED: %', what; END IF; RAISE NOTICE 'ok - %', what; END $$;

INSERT INTO auth.users(id, email) VALUES
  ('a0000000-0000-4000-8000-000000000001', 'arjun@example.com'),
  ('b0000000-0000-4000-8000-000000000002', 'meera@example.com'),
  ('c0000000-0000-4000-8000-000000000003', 'teen@example.com');
GRANT EXECUTE ON FUNCTION pg_temp.as_user(uuid), pg_temp.expect_error(text, text), pg_temp.ok(boolean, text) TO authenticated;

-- ---------------------------------------------------------------- onboarding → mind
SELECT pg_temp.as_user('a0000000-0000-4000-8000-000000000001');
INSERT INTO public.mini_profiles(user_id, display_name, companion_mode, tone, focus, boundaries, birth_year, consented_at)
VALUES ('a0000000-0000-4000-8000-000000000001', 'Arjun', 'friend', 'balanced', 'Launching my startup', 'My ex', extract(year from now())::int - 31, now());
SELECT pg_temp.ok((SELECT preferred_name = 'Arjun' FROM public.mind_persons), 'onboarding creates the person');
SELECT pg_temp.ok((SELECT count(*) = 5 FROM public.mind_facts WHERE source = 'user_stated'), 'onboarding answers become user-stated facts');
SELECT pg_temp.ok((SELECT sensitivity_level = 'L3' FROM public.mind_facts WHERE field_key = 'topics_they_do_not_want_discussed'),
  'boundaries are stored at the field''s L3 level, never lower');
SELECT pg_temp.ok((public.mind_context_package() -> 'stage' ->> 'title') = 'Early adulthood', 'Arjun (31) is in Early adulthood');
SELECT pg_temp.ok(jsonb_array_length(public.mind_context_package() -> 'avoid_topics') = 1, 'avoid-topics reach Mini');
RESET ROLE;

SELECT pg_temp.as_user('b0000000-0000-4000-8000-000000000002');
INSERT INTO public.mini_profiles(user_id, display_name, companion_mode, tone, birth_year, consented_at)
VALUES ('b0000000-0000-4000-8000-000000000002', 'Meera', 'both', 'gentle', extract(year from now())::int - 52, now());
SELECT pg_temp.ok((public.mind_context_package() -> 'stage' ->> 'title') = 'Mature adulthood', 'Meera (52) is in Mature adulthood');
SELECT pg_temp.ok((public.mind_context_package() -> 'stage' -> 'persona' ->> 'voice') IS NOT NULL, 'stage persona reaches Mini');
-- each person sees only their own mind
SELECT pg_temp.ok((SELECT count(*) = 0 FROM public.mind_facts WHERE user_id = 'a0000000-0000-4000-8000-000000000001'), 'Meera cannot see Arjun''s facts');
SELECT pg_temp.ok((SELECT count(*) = 1 FROM public.mind_persons), 'Meera sees only her own person row');
SELECT pg_temp.expect_error($$INSERT INTO public.mind_facts(user_id, field_key, group_id, attribute_name, value, source, sensitivity_level)
  VALUES ('a0000000-0000-4000-8000-000000000001', 'music', 17, 'Music', 'jazz', 'user_stated', 'L1')$$, 'row-level security');
RESET ROLE;

-- ---------------------------------------------------------------- doc rules
SELECT pg_temp.as_user('a0000000-0000-4000-8000-000000000001');
-- AI observations are never stored as confirmed facts
SELECT pg_temp.expect_error($$INSERT INTO public.mind_facts(user_id, field_key, group_id, attribute_name, value, source, sensitivity_level)
  VALUES (auth.uid(), 'music', 17, 'Music', 'loves jazz', 'ai_observed', 'L1')$$, 'mind_facts_ai_not_confirmed');
INSERT INTO public.mind_facts(user_id, field_key, group_id, attribute_name, value, source, sensitivity_level, consent_status, verification_status, confidence)
  VALUES (auth.uid(), 'music', 17, 'Music', 'loves jazz', 'ai_observed', 'L1', 'pending', 'unverified_inference', 0.6);
SELECT pg_temp.ok((SELECT count(*) = 1 FROM public.mind_facts WHERE consent_status = 'pending'), 'AI observation waits for confirmation ("keep?")');
SELECT pg_temp.ok(NOT ((public.mind_context_package() -> 'facts')::text LIKE '%jazz%'), 'unconfirmed guesses never reach Mini''s context');
-- hypotheses stay uncertain
SELECT pg_temp.expect_error($$INSERT INTO public.mind_facts(user_id, field_key, group_id, attribute_name, value, source, sensitivity_level, consent_status, verification_status, confidence)
  VALUES (auth.uid(), 'curiosity', 4, 'Curiosity', 'very curious', 'ai_hypothesis', 'L1', 'pending', 'unverified_inference', 0.9)$$, 'mind_facts_hypothesis_uncertain');
-- never infer religion, health, money, fears
SELECT pg_temp.expect_error($$INSERT INTO public.mind_facts(user_id, field_key, group_id, attribute_name, value, source, sensitivity_level, consent_status, verification_status, confidence)
  VALUES (auth.uid(), 'religious_affiliation', 20, 'Religion', 'guess', 'ai_observed', 'L3', 'pending', 'unverified_inference', 0.5)$$, 'may not infer');
-- but the person may state it
INSERT INTO public.mind_facts(user_id, field_key, group_id, attribute_name, value, source, sensitivity_level)
  VALUES (auth.uid(), 'meditation_practices', 20, 'Meditation', 'meditates every morning', 'user_stated', 'L1');
SELECT pg_temp.ok((SELECT sensitivity_level = 'L3' FROM public.mind_facts WHERE field_key = 'meditation_practices'), 'religion & spirituality facts are always L3');
SELECT pg_temp.ok(NOT ((public.mind_context_package() -> 'facts')::text LIKE '%meditates%'), 'L3 facts are excluded from the default (L2) companion context');
-- L4 / never-store / secrets
SELECT pg_temp.expect_error($$INSERT INTO public.mind_facts(user_id, field_key, group_id, attribute_name, value, source, sensitivity_level)
  VALUES (auth.uid(), 'personal_identification_documents', 1, 'Passport', 'X1234567', 'user_stated', 'L2')$$, 'must never be stored');
SELECT pg_temp.expect_error($$INSERT INTO public.mind_facts(user_id, field_key, group_id, attribute_name, value, source, sensitivity_level)
  VALUES (auth.uid(), 'security_preferences', 27, 'Security', 'my password is hunter2', 'user_stated', 'L2')$$, 'secrets are never stored');
SELECT pg_temp.expect_error($$INSERT INTO public.mind_facts(user_id, field_key, group_id, attribute_name, value, source, sensitivity_level)
  VALUES (auth.uid(), 'music', 17, 'Music', 'x', 'user_stated', 'L4')$$, 'mind_facts_sensitivity_level_check');
-- versions + audit
UPDATE public.mind_facts SET value = 'Launching my startup this month' WHERE field_key = 'topics_they_enjoy_discussing';
SELECT pg_temp.ok((SELECT count(*) >= 1 FROM public.mind_fact_versions), 'every change keeps the previous version');
SELECT pg_temp.ok((SELECT count(*) >= 8 FROM public.mind_audit_log), 'every write is audited');
SELECT pg_temp.expect_error($$INSERT INTO public.mind_audit_log(user_id, actor, action, table_name) VALUES (auth.uid(), 'me', 'x', 'y')$$, 'permission denied');
-- predictions never become certain
SELECT pg_temp.expect_error($$INSERT INTO public.mind_insights(user_id, layer, statement, confidence)
  VALUES (auth.uid(), 'predictive', 'Will burn out', 0.95)$$, 'mind_insights_predictions_uncertain');
INSERT INTO public.mind_insights(user_id, layer, statement, confidence)
  VALUES (auth.uid(), 'contextual', 'Startup ambition may compete with family time', 0.6);
-- health/finance need their own consent
SELECT pg_temp.expect_error($$INSERT INTO public.mind_health_records(user_id, field_key, value) VALUES (auth.uid(), 'sleep_quality', 'poor lately')$$, 'separate consent');
INSERT INTO public.mind_consents(user_id, scope) VALUES (auth.uid(), 'store_health');
INSERT INTO public.mind_health_records(user_id, field_key, value) VALUES (auth.uid(), 'sleep_quality', 'poor lately');
SELECT pg_temp.expect_error($$INSERT INTO public.mind_health_records(user_id, field_key, value) VALUES (auth.uid(), 'savings', 'x')$$, 'group 03');
-- timeline, follow-ups, people, goals → context package
INSERT INTO public.mind_life_events(user_id, occurred_on, title, emotion, follow_up_at, follow_up_question)
  VALUES (auth.uid(), current_date - 1, 'Pitched the startup to an investor', 'nervous', now() - interval '1 hour', 'How did the investor pitch go?');
INSERT INTO public.mind_people(user_id, name, relation, closeness) VALUES (auth.uid(), 'Bruno', 'dog', 5);
INSERT INTO public.mind_goals(user_id, title, horizon, area, progress) VALUES (auth.uid(), 'Launch the startup', 'short', 'business', 40);
SELECT pg_temp.ok((public.mind_context_package() -> 'follow_ups' -> 0 ->> 'ask') = 'How did the investor pitch go?', 'yesterday''s event becomes today''s follow-up');
SELECT pg_temp.ok((public.mind_context_package() -> 'people' -> 0 ->> 'name') = 'Bruno', 'people in their life reach Mini');
SELECT pg_temp.ok((public.mind_context_package() -> 'goals' -> 0 ->> 'title') = 'Launch the startup', 'goals reach Mini');
SELECT pg_temp.ok((public.mind_context_package() -> 'insights' -> 0 ->> 'layer') = 'contextual', 'contextual insight reaches Mini');
-- curiosity: one new question, non-sensitive first, never repeated
SELECT pg_temp.ok((public.mind_context_package() -> 'next_question' ->> 'topic') = 'Career development', 'first curiosity question follows the stage focus');
INSERT INTO public.mind_questions_asked(user_id, focus_id, question)
  SELECT auth.uid(), public.mind_context_package() -> 'next_question' ->> 'focus_id', public.mind_context_package() -> 'next_question' ->> 'ask';
SELECT pg_temp.ok((public.mind_context_package() -> 'next_question' ->> 'ask') <> 'How''s work treating you these days?', 'an asked question is not repeated');
SELECT pg_temp.ok(NOT ((public.mind_context_package() -> 'next_question' ->> 'topic') IN ('Financial planning','Housing and assets')),
  'sensitive topics wait until trust is built (5+ conversations)');
-- sync score
INSERT INTO public.mind_facts(user_id, field_key, group_id, attribute_name, value, source, sensitivity_level)
  VALUES (auth.uid(), 'job_title', 14, 'Job title', 'Founder', 'user_stated', 'L2');
SELECT pg_temp.ok(((public.mind_sync_score() ->> 'score')::int BETWEEN 1 AND 100), 'sync score is computed (' || (public.mind_sync_score() ->> 'score') || '%)');
SELECT pg_temp.ok(((public.mind_sync_score() ->> 'core_known')::int >= 1), 'stage-core coverage counts confirmed facts');
RESET ROLE;

-- ---------------------------------------------------------------- children are never profiled
SELECT pg_temp.as_user('c0000000-0000-4000-8000-000000000003');
INSERT INTO public.mini_profiles(user_id, display_name, birth_year, consented_at)
VALUES ('c0000000-0000-4000-8000-000000000003', 'Kid', extract(year from now())::int - 15, now());
SELECT pg_temp.ok((SELECT count(*) = 0 FROM public.mind_facts), 'no facts are created for a 15-year-old');
SELECT pg_temp.expect_error($$INSERT INTO public.mind_facts(user_id, field_key, group_id, attribute_name, value, source, sensitivity_level)
  VALUES (auth.uid(), 'music', 17, 'Music', 'pop', 'user_stated', 'L1')$$, 'under 18');
SELECT pg_temp.ok((public.mind_context_package() ->> 'reason') = 'adults_only', 'Mini gets no profile context for minors');
RESET ROLE;

-- ---------------------------------------------------------------- delete account wipes the mind
SELECT pg_temp.as_user('a0000000-0000-4000-8000-000000000001');
SELECT public.mini_delete_my_account();
RESET ROLE;
SELECT pg_temp.ok((SELECT count(*) = 0 FROM public.mind_facts WHERE user_id = 'a0000000-0000-4000-8000-000000000001'), 'deleting the account erases facts');
SELECT pg_temp.ok((SELECT count(*) = 0 FROM public.mind_life_events WHERE user_id = 'a0000000-0000-4000-8000-000000000001')
  AND (SELECT count(*) = 0 FROM public.mind_audit_log WHERE user_id = 'a0000000-0000-4000-8000-000000000001'), 'and the timeline and audit trail');
SELECT pg_temp.ok((SELECT count(*) > 0 FROM public.mind_facts WHERE user_id = 'b0000000-0000-4000-8000-000000000002'), 'Meera''s mind is untouched');
