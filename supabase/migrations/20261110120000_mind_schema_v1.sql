-- Mini's mind — Universal Human Context Database (UHCD) v1
-- Implements docs/HUMAN-INTELLIGENCE-DATABASE.md for adults (18–100+).
-- Every per-person table is owned by the person (auth.uid()) via RLS; the
-- voice worker reads/writes with the person's own token, never a service key.
--
-- Doc rules enforced IN THE DATABASE (not just in app code):
--  * AI observations / hypotheses are never stored as confirmed facts (sec 5, 10)
--  * L4 data and forbidden fields are never stored (sec 6, group 27 note)
--  * AI may not infer religion, health, finances, fears, identity fields (groups 03/15/20/23)
--  * Predictions stay uncertain (sec 4 layer 4)
--  * No profiling of children: facts are refused for people under 18 (sec 6)
--  * Every change is versioned and audited (sec 8: memory_versions, audit_logs)

-- ============================================================ reference data
CREATE TABLE IF NOT EXISTS public.mind_taxonomy_versions (
  version text PRIMARY KEY,
  source text NOT NULL,
  loaded_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.mind_groups (
  id smallint PRIMARY KEY CHECK (id BETWEEN 1 AND 30),
  title text NOT NULL,
  meaning text NOT NULL DEFAULT '',
  intro text NOT NULL DEFAULT '',
  notes text[] NOT NULL DEFAULT '{}',
  default_level text NOT NULL CHECK (default_level IN ('L0','L1','L2','L3','L4')),
  ai_may_infer boolean NOT NULL
);

CREATE TABLE IF NOT EXISTS public.mind_fields (
  key text PRIMARY KEY,
  group_id smallint NOT NULL REFERENCES public.mind_groups(id),
  label text NOT NULL,
  optional boolean NOT NULL DEFAULT false,
  level text NOT NULL CHECK (level IN ('L0','L1','L2','L3','L4')),
  never_store boolean NOT NULL DEFAULT false,
  ai_may_infer boolean NOT NULL,
  data_type text NOT NULL DEFAULT 'text',
  facets text[] NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS mind_fields_group_idx ON public.mind_fields(group_id);

CREATE TABLE IF NOT EXISTS public.mind_life_stages (
  stage smallint PRIMARY KEY CHECK (stage BETWEEN 1 AND 8),
  code text NOT NULL UNIQUE,
  title text NOT NULL,
  min_age smallint NOT NULL,
  max_age smallint,                         -- NULL = no upper bound (100+)
  theme text NOT NULL,
  persona jsonb NOT NULL DEFAULT '{}'::jsonb,
  available boolean NOT NULL DEFAULT false   -- adults now; children with parental consent later
);

CREATE TABLE IF NOT EXISTS public.mind_stage_focus (
  id text PRIMARY KEY,                        -- e.g. 's3_01'
  stage smallint NOT NULL REFERENCES public.mind_life_stages(stage),
  ord smallint NOT NULL,
  item text NOT NULL,
  group_ids smallint[] NOT NULL,
  field_keys text[] NOT NULL DEFAULT '{}',
  sensitive boolean NOT NULL DEFAULT false,
  only_if_user_raises boolean NOT NULL DEFAULT false,
  questions text[] NOT NULL DEFAULT '{}',
  UNIQUE (stage, ord)
);

-- ============================================================ person
CREATE TABLE IF NOT EXISTS public.mind_persons (
  user_id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  birth_year smallint CHECK (birth_year IS NULL OR birth_year BETWEEN 1900 AND 2100),
  preferred_name text NOT NULL DEFAULT '' CHECK (char_length(preferred_name) <= 80),
  adopted_at timestamptz,                     -- first conversation: Mini "adopts" this person
  last_talk_at timestamptz,
  conversations smallint NOT NULL DEFAULT 0 CHECK (conversations >= 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION public.mind_stage_for_age(age int)
RETURNS smallint LANGUAGE sql IMMUTABLE SET search_path = '' AS $$
  SELECT CASE WHEN age IS NULL THEN NULL
    WHEN age < 13 THEN 1 WHEN age < 18 THEN 2 WHEN age < 25 THEN 3 WHEN age < 35 THEN 4
    WHEN age < 50 THEN 5 WHEN age < 65 THEN 6 WHEN age < 80 THEN 7 ELSE 8 END::smallint
$$;

CREATE OR REPLACE FUNCTION public.mind_person_age(p_user uuid)
RETURNS int LANGUAGE sql STABLE SET search_path = '' AS $$
  SELECT extract(year FROM now())::int - birth_year FROM public.mind_persons WHERE user_id = p_user
$$;

-- ============================================================ sources (memory_sources)
CREATE TABLE IF NOT EXISTS public.mind_sources (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  kind text NOT NULL CHECK (kind IN ('conversation','onboarding','manual','import')),
  started_at timestamptz NOT NULL DEFAULT now(),
  ended_at timestamptz,
  mood text CHECK (mood IS NULL OR char_length(mood) <= 40),
  summary text NOT NULL DEFAULT '' CHECK (char_length(summary) <= 600),  -- never a transcript
  UNIQUE (id, user_id)
);

-- ============================================================ facts (human_attributes)
CREATE TABLE IF NOT EXISTS public.mind_facts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,       -- person_id
  field_key text REFERENCES public.mind_fields(key),                        -- attribute_id
  group_id smallint NOT NULL REFERENCES public.mind_groups(id),             -- category
  attribute_name text NOT NULL CHECK (char_length(attribute_name) BETWEEN 1 AND 120),
  value text NOT NULL CHECK (char_length(value) BETWEEN 1 AND 1000),
  value_json jsonb,                                                         -- structured value / interest facets
  data_type text NOT NULL DEFAULT 'text',
  layer text NOT NULL DEFAULT 'descriptive' CHECK (layer IN ('descriptive','contextual','temporal')),
  context text CHECK (context IS NULL OR char_length(context) <= 500),       -- why it matters
  source text NOT NULL CHECK (source IN ('user_stated','user_confirmed','ai_observed','ai_hypothesis','imported')),
  source_id uuid,
  confidence real NOT NULL DEFAULT 0.9 CHECK (confidence > 0 AND confidence <= 1),
  verification_status text NOT NULL DEFAULT 'self_reported'
    CHECK (verification_status IN ('self_reported','user_confirmed','externally_verified','unverified_inference')),
  sensitivity_level text NOT NULL CHECK (sensitivity_level IN ('L0','L1','L2','L3')),  -- L4 never stored here
  consent_status text NOT NULL DEFAULT 'granted' CHECK (consent_status IN ('granted','pending','revoked')),
  permitted_ai_agents text[] NOT NULL DEFAULT '{mini}',
  visibility text NOT NULL DEFAULT 'private' CHECK (visibility IN ('private','shared_with_agents')),
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','outdated','superseded','deleted')),  -- deletion_status
  valid_from timestamptz NOT NULL DEFAULT now(),
  valid_until timestamptz,
  last_confirmed_at timestamptz,
  expiration_policy text NOT NULL DEFAULT 'review_12_months'
    CHECK (expiration_policy IN ('never','review_3_months','review_6_months','review_12_months','expire_at_valid_until')),
  review_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (source_id, user_id) REFERENCES public.mind_sources(id, user_id) ON DELETE SET NULL (source_id),
  -- AI inferences are never stored as if user-confirmed (doc sec 5 critical distinction)
  CONSTRAINT mind_facts_ai_not_confirmed CHECK (
    source NOT IN ('ai_observed','ai_hypothesis')
    OR (verification_status = 'unverified_inference' AND consent_status IN ('pending','revoked') AND confidence < 1)),
  CONSTRAINT mind_facts_hypothesis_uncertain CHECK (source <> 'ai_hypothesis' OR confidence <= 0.7)
);
CREATE INDEX IF NOT EXISTS mind_facts_user_idx ON public.mind_facts(user_id, status, group_id);
CREATE INDEX IF NOT EXISTS mind_facts_field_idx ON public.mind_facts(user_id, field_key) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS mind_facts_pending_idx ON public.mind_facts(user_id) WHERE consent_status = 'pending';

CREATE OR REPLACE FUNCTION public.mind_facts_guard()
RETURNS trigger LANGUAGE plpgsql SET search_path = '' AS $$
DECLARE f public.mind_fields%ROWTYPE; age int;
BEGIN
  IF (select auth.uid()) IS NOT NULL AND NEW.user_id <> (select auth.uid()) THEN
    RAISE EXCEPTION 'mind: row-level security — a mind can only be written by its owner';
  END IF;
  age := public.mind_person_age(NEW.user_id);
  IF age IS NULL OR age < 18 THEN
    RAISE EXCEPTION 'mind: no profile facts for people under 18 or without a confirmed age';
  END IF;
  IF NEW.field_key IS NOT NULL THEN
    SELECT * INTO f FROM public.mind_fields WHERE key = NEW.field_key;
    IF f.never_store OR f.level = 'L4' THEN
      RAISE EXCEPTION 'mind: field % must never be stored', NEW.field_key;
    END IF;
    NEW.group_id := f.group_id;
    IF NEW.source IN ('ai_observed','ai_hypothesis') AND NOT f.ai_may_infer THEN
      RAISE EXCEPTION 'mind: AI may not infer %; only the person can state it', NEW.field_key;
    END IF;
    -- sensitivity can be raised by the writer, never lowered below the field level
    IF NEW.sensitivity_level < f.level THEN NEW.sensitivity_level := f.level; END IF;
  END IF;
  IF NEW.source IN ('ai_observed','ai_hypothesis')
     AND (SELECT ai_may_infer FROM public.mind_groups WHERE id = NEW.group_id) IS FALSE THEN
    RAISE EXCEPTION 'mind: AI may not infer facts in group %', NEW.group_id;
  END IF;
  -- secrets never belong in a human profile (group 27 note)
  IF NEW.value ~* '(password|passcode|otp|private key|seed phrase|recovery code|cvv|pin\s*[:=]?\s*\d{4})' THEN
    RAISE EXCEPTION 'mind: secrets are never stored in a human profile';
  END IF;
  IF NEW.source IN ('user_stated','user_confirmed') AND NEW.last_confirmed_at IS NULL THEN
    NEW.last_confirmed_at := now();
  END IF;
  NEW.review_at := CASE NEW.expiration_policy
    WHEN 'review_3_months' THEN coalesce(NEW.last_confirmed_at, now()) + interval '3 months'
    WHEN 'review_6_months' THEN coalesce(NEW.last_confirmed_at, now()) + interval '6 months'
    WHEN 'review_12_months' THEN coalesce(NEW.last_confirmed_at, now()) + interval '12 months'
    WHEN 'expire_at_valid_until' THEN NEW.valid_until ELSE NULL END;
  NEW.updated_at := now();
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS mind_facts_guard ON public.mind_facts;
CREATE TRIGGER mind_facts_guard BEFORE INSERT OR UPDATE ON public.mind_facts
  FOR EACH ROW EXECUTE FUNCTION public.mind_facts_guard();

-- memory_versions: every change to a fact keeps the previous version
CREATE TABLE IF NOT EXISTS public.mind_fact_versions (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  fact_id uuid NOT NULL,
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  old_row jsonb NOT NULL,
  changed_at timestamptz NOT NULL DEFAULT now(),
  operation text NOT NULL
);
CREATE INDEX IF NOT EXISTS mind_fact_versions_idx ON public.mind_fact_versions(user_id, fact_id);
CREATE OR REPLACE FUNCTION public.mind_version_fact()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
BEGIN
  -- account deletion cascades here: keep nothing about a deleted person
  IF NOT EXISTS (SELECT 1 FROM auth.users WHERE id = OLD.user_id) THEN RETURN NULL; END IF;
  INSERT INTO public.mind_fact_versions(fact_id, user_id, old_row, operation)
  VALUES (OLD.id, OLD.user_id, to_jsonb(OLD), TG_OP);
  RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS mind_version_fact ON public.mind_facts;
CREATE TRIGGER mind_version_fact AFTER UPDATE OR DELETE ON public.mind_facts
  FOR EACH ROW EXECUTE FUNCTION public.mind_version_fact();

-- ============================================================ timeline (life_events / memories)
CREATE TABLE IF NOT EXISTS public.mind_life_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  occurred_on date NOT NULL DEFAULT current_date,
  title text NOT NULL CHECK (char_length(title) BETWEEN 1 AND 160),
  summary text NOT NULL DEFAULT '' CHECK (char_length(summary) <= 600),
  emotion text CHECK (emotion IS NULL OR char_length(emotion) <= 40),
  importance smallint NOT NULL DEFAULT 2 CHECK (importance BETWEEN 1 AND 5),
  group_ids smallint[] NOT NULL DEFAULT '{29}',
  kind text NOT NULL DEFAULT 'day' CHECK (kind IN ('day','milestone','memory','upcoming')),
  follow_up_at timestamptz,                     -- e.g. the day after "exam on Friday"
  follow_up_question text CHECK (follow_up_question IS NULL OR char_length(follow_up_question) <= 200),
  followed_up_at timestamptz,
  source text NOT NULL DEFAULT 'user_stated' CHECK (source IN ('user_stated','user_confirmed','ai_observed')),
  consent_status text NOT NULL DEFAULT 'granted' CHECK (consent_status IN ('granted','pending','revoked')),
  never_revisit boolean NOT NULL DEFAULT false,  -- "experiences they do not want AI to revisit"
  source_id uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS mind_life_events_idx ON public.mind_life_events(user_id, occurred_on DESC);
CREATE INDEX IF NOT EXISTS mind_life_events_followup_idx ON public.mind_life_events(user_id, follow_up_at)
  WHERE followed_up_at IS NULL AND follow_up_at IS NOT NULL;

-- ============================================================ relationship graph
CREATE TABLE IF NOT EXISTS public.mind_people (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  name text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 80),
  relation text NOT NULL CHECK (char_length(relation) BETWEEN 1 AND 60),   -- mother, best friend, dog…
  group_id smallint NOT NULL DEFAULT 10 CHECK (group_id IN (9, 10)),
  closeness smallint CHECK (closeness IS NULL OR closeness BETWEEN 1 AND 5),
  birthday date,
  notes text NOT NULL DEFAULT '' CHECK (char_length(notes) <= 400),
  avoid boolean NOT NULL DEFAULT false,          -- "people they avoid"
  source text NOT NULL DEFAULT 'user_stated' CHECK (source IN ('user_stated','user_confirmed','ai_observed')),
  consent_status text NOT NULL DEFAULT 'granted' CHECK (consent_status IN ('granted','pending','revoked')),
  last_mentioned_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, name, relation)
);

-- Graph edges between anything in the mind (doc sec 7: graph model in Postgres first).
CREATE TABLE IF NOT EXISTS public.mind_relations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  subject_type text NOT NULL CHECK (subject_type IN ('self','person','fact','event','goal','project')),
  subject_id uuid,
  predicate text NOT NULL CHECK (char_length(predicate) BETWEEN 1 AND 60),  -- 'supports', 'conflicts_with', 'pet_of'…
  object_type text NOT NULL CHECK (object_type IN ('self','person','fact','event','goal','project')),
  object_id uuid,
  weight real NOT NULL DEFAULT 1 CHECK (weight > 0 AND weight <= 10),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS mind_relations_idx ON public.mind_relations(user_id, subject_type, subject_id);

-- ============================================================ goals, projects, routines
CREATE TABLE IF NOT EXISTS public.mind_goals (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  title text NOT NULL CHECK (char_length(title) BETWEEN 1 AND 200),
  horizon text NOT NULL DEFAULT 'medium' CHECK (horizon IN ('short','medium','long')),
  area text NOT NULL DEFAULT 'personal' CHECK (area IN ('personal','educational','career','financial','health','family',
    'relationship','travel','business','creative','social_contribution','retirement')),
  target_date date,
  success_measure text CHECK (success_measure IS NULL OR char_length(success_measure) <= 300),
  required_resources text CHECK (required_resources IS NULL OR char_length(required_resources) <= 300),
  obstacles text CHECK (obstacles IS NULL OR char_length(obstacles) <= 300),
  motivation text CHECK (motivation IS NULL OR char_length(motivation) <= 300),
  progress smallint NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
  priority smallint NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','completed','abandoned','paused')),
  source text NOT NULL DEFAULT 'user_stated' CHECK (source IN ('user_stated','user_confirmed','ai_observed')),
  consent_status text NOT NULL DEFAULT 'granted' CHECK (consent_status IN ('granted','pending','revoked')),
  last_checked_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.mind_projects (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  title text NOT NULL CHECK (char_length(title) BETWEEN 1 AND 200),
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','completed','abandoned','paused')),
  started_on date, ended_on date,
  notes text NOT NULL DEFAULT '' CHECK (char_length(notes) <= 600),
  goal_id uuid REFERENCES public.mind_goals(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.mind_routines (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  kind text NOT NULL CHECK (kind IN ('wake','sleep','morning','evening','work','meal','exercise','study','weekend','ritual','other')),
  at_time time,
  days text[] NOT NULL DEFAULT '{mon,tue,wed,thu,fri,sat,sun}',
  description text NOT NULL CHECK (char_length(description) BETWEEN 1 AND 300),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- ============================================================ compartmentalized L3 records
-- Health (doc: private, highly protected; distinguish verified / self-reported / AI observation;
-- the AI must not diagnose). Only the person writes these; AI observations are not allowed here.
CREATE TABLE IF NOT EXISTS public.mind_health_records (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  field_key text NOT NULL REFERENCES public.mind_fields(key),
  value text NOT NULL CHECK (char_length(value) BETWEEN 1 AND 600),
  basis text NOT NULL DEFAULT 'self_reported' CHECK (basis IN ('self_reported','medically_verified')),
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','resolved','outdated')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
-- Finances (doc: compartmentalized; an education agent never needs the bank balance).
CREATE TABLE IF NOT EXISTS public.mind_financial_records (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  field_key text NOT NULL REFERENCES public.mind_fields(key),
  value text NOT NULL CHECK (char_length(value) BETWEEN 1 AND 600),
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','outdated')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE OR REPLACE FUNCTION public.mind_compartment_guard()
RETURNS trigger LANGUAGE plpgsql SET search_path = '' AS $$
DECLARE g smallint; age int;
BEGIN
  age := public.mind_person_age(NEW.user_id);
  IF age IS NULL OR age < 18 THEN RAISE EXCEPTION 'mind: adults only'; END IF;
  SELECT group_id INTO g FROM public.mind_fields WHERE key = NEW.field_key;
  IF TG_TABLE_NAME = 'mind_health_records' AND g <> 3 THEN RAISE EXCEPTION 'mind: health records need a group 03 field'; END IF;
  IF TG_TABLE_NAME = 'mind_financial_records' AND g <> 15 THEN RAISE EXCEPTION 'mind: financial records need a group 15 field'; END IF;
  IF NOT EXISTS (SELECT 1 FROM public.mind_consents c WHERE c.user_id = NEW.user_id AND c.revoked_at IS NULL
                 AND c.scope = CASE WHEN g = 3 THEN 'store_health' ELSE 'store_finances' END) THEN
    RAISE EXCEPTION 'mind: separate consent required for %', CASE WHEN g = 3 THEN 'health' ELSE 'financial' END;
  END IF;
  NEW.updated_at := now();
  RETURN NEW;
END $$;

-- ============================================================ intelligence layers 2–5
-- contextual (why it matters / conflicts), predictive (what might happen — never a fact),
-- partnership (how Mini can help without taking control).
CREATE TABLE IF NOT EXISTS public.mind_insights (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  layer text NOT NULL CHECK (layer IN ('contextual','temporal','predictive','partnership')),
  statement text NOT NULL CHECK (char_length(statement) BETWEEN 1 AND 400),
  basis_fact_ids uuid[] NOT NULL DEFAULT '{}',
  confidence real NOT NULL CHECK (confidence > 0 AND confidence < 1),   -- never certainty
  status text NOT NULL DEFAULT 'open' CHECK (status IN ('open','shared','accepted','dismissed','expired')),
  expires_at timestamptz NOT NULL DEFAULT now() + interval '30 days',
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT mind_insights_predictions_uncertain CHECK (layer <> 'predictive' OR confidence <= 0.8)
);

-- ============================================================ consent & permissions
CREATE TABLE IF NOT EXISTS public.mind_consents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  scope text NOT NULL CHECK (scope IN ('core_profile','learn_from_conversations','proactive_followups',
    'store_health','store_finances','stories_from_my_life','share_with_other_agents')),
  policy_version text NOT NULL DEFAULT '2026-11-10',
  granted_at timestamptz NOT NULL DEFAULT now(),
  revoked_at timestamptz
);
CREATE UNIQUE INDEX IF NOT EXISTS mind_consents_active_idx ON public.mind_consents(user_id, scope) WHERE revoked_at IS NULL;

DROP TRIGGER IF EXISTS mind_health_guard ON public.mind_health_records;
CREATE TRIGGER mind_health_guard BEFORE INSERT OR UPDATE ON public.mind_health_records
  FOR EACH ROW EXECUTE FUNCTION public.mind_compartment_guard();
DROP TRIGGER IF EXISTS mind_finance_guard ON public.mind_financial_records;
CREATE TRIGGER mind_finance_guard BEFORE INSERT OR UPDATE ON public.mind_financial_records
  FOR EACH ROW EXECUTE FUNCTION public.mind_compartment_guard();

-- Per agent, purpose and period (doc sec 6).
CREATE TABLE IF NOT EXISTS public.mind_agent_permissions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  agent text NOT NULL CHECK (char_length(agent) BETWEEN 1 AND 40),          -- 'mini'
  purpose text NOT NULL CHECK (char_length(purpose) BETWEEN 1 AND 80),       -- 'companion_conversation'
  max_level text NOT NULL DEFAULT 'L2' CHECK (max_level IN ('L0','L1','L2','L3')),
  group_ids smallint[],                                                      -- NULL = all permitted groups
  granted_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz,
  revoked_at timestamptz,
  UNIQUE (user_id, agent, purpose)
);

-- ============================================================ feedback, questions, snapshots
CREATE TABLE IF NOT EXISTS public.mind_feedback (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  target_type text NOT NULL CHECK (target_type IN ('fact','insight','event','person','goal')),
  target_id uuid NOT NULL,
  action text NOT NULL CHECK (action IN ('confirm','correct','reject','delete','never_mention')),
  note text CHECK (note IS NULL OR char_length(note) <= 300),
  created_at timestamptz NOT NULL DEFAULT now()
);

-- Which curiosity questions Mini already asked (never interrogate, never repeat).
CREATE TABLE IF NOT EXISTS public.mind_questions_asked (
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  focus_id text NOT NULL REFERENCES public.mind_stage_focus(id),
  question text NOT NULL,
  asked_at timestamptz NOT NULL DEFAULT now(),
  answered boolean,
  PRIMARY KEY (user_id, focus_id, question)
);

CREATE TABLE IF NOT EXISTS public.mind_context_snapshots (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  agent text NOT NULL,
  purpose text NOT NULL,
  package jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL DEFAULT now() + interval '1 day'
);

-- ============================================================ audit log
CREATE TABLE IF NOT EXISTS public.mind_audit_log (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  actor text NOT NULL,                     -- database role + agent header if any
  action text NOT NULL,
  table_name text NOT NULL,
  row_id text,
  at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS mind_audit_idx ON public.mind_audit_log(user_id, at DESC);
CREATE OR REPLACE FUNCTION public.mind_audit()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE r record; agent text;
BEGIN
  r := CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
  IF NOT EXISTS (SELECT 1 FROM auth.users WHERE id = r.user_id) THEN RETURN NULL; END IF;  -- account being deleted
  BEGIN agent := current_setting('request.headers', true)::json ->> 'x-mini-agent';
  EXCEPTION WHEN others THEN agent := NULL; END;
  INSERT INTO public.mind_audit_log(user_id, actor, action, table_name, row_id)
  VALUES (r.user_id, current_user || coalesce(':' || left(agent, 30), ''), TG_OP, TG_TABLE_NAME,
          coalesce(to_jsonb(r) ->> 'id', to_jsonb(r) ->> 'focus_id', r.user_id::text));
  RETURN NULL;
END $$;

-- ============================================================ RLS + grants + audit/updated triggers
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['mind_persons','mind_sources','mind_facts','mind_fact_versions','mind_life_events',
    'mind_people','mind_relations','mind_goals','mind_projects','mind_routines','mind_health_records',
    'mind_financial_records','mind_insights','mind_consents','mind_agent_permissions','mind_feedback',
    'mind_questions_asked','mind_context_snapshots','mind_audit_log']
  LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('REVOKE ALL ON public.%I FROM anon', t);
    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_own', t);
    IF t IN ('mind_fact_versions','mind_audit_log') THEN
      -- history is readable by its owner, written only by triggers
      EXECUTE format('CREATE POLICY %I ON public.%I FOR SELECT TO authenticated USING (user_id = (select auth.uid()))', t || '_own', t);
      EXECUTE format('GRANT SELECT ON public.%I TO authenticated', t);
    ELSE
      EXECUTE format('CREATE POLICY %I ON public.%I FOR ALL TO authenticated USING (user_id = (select auth.uid())) WITH CHECK (user_id = (select auth.uid()))', t || '_own', t);
      EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON public.%I TO authenticated', t);
    END IF;
    IF t NOT IN ('mind_fact_versions','mind_audit_log') THEN
      EXECUTE format('DROP TRIGGER IF EXISTS mind_audit ON public.%I', t);
      EXECUTE format('CREATE TRIGGER mind_audit AFTER INSERT OR UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.mind_audit()', t);
    END IF;
  END LOOP;
  FOREACH t IN ARRAY ARRAY['mind_taxonomy_versions','mind_groups','mind_fields','mind_life_stages','mind_stage_focus']
  LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_read', t);
    EXECUTE format('CREATE POLICY %I ON public.%I FOR SELECT TO authenticated USING (true)', t || '_read', t);
    EXECUTE format('REVOKE ALL ON public.%I FROM anon', t);
    EXECUTE format('GRANT SELECT ON public.%I TO authenticated', t);
  END LOOP;
END $$;

-- ============================================================ person bootstrap from the app profile
-- The mobile app onboarding writes mini_profiles; mirror it into the mind so
-- Mini "adopts" the person with what they told it on day one.
CREATE OR REPLACE FUNCTION public.mind_sync_from_profile()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
BEGIN
  INSERT INTO public.mind_persons(user_id, birth_year, preferred_name)
  VALUES (NEW.user_id, NEW.birth_year, NEW.display_name)
  ON CONFLICT (user_id) DO UPDATE SET birth_year = EXCLUDED.birth_year,
    preferred_name = EXCLUDED.preferred_name, updated_at = now();
  IF NEW.birth_year IS NULL OR extract(year FROM now())::int - NEW.birth_year < 18 THEN
    RETURN NEW;   -- nothing more for minors or unknown age
  END IF;
  INSERT INTO public.mind_consents(user_id, scope) VALUES (NEW.user_id, 'core_profile')
    ON CONFLICT DO NOTHING;
  -- onboarding answers become user-stated facts (re-stated answers supersede old ones)
  UPDATE public.mind_facts SET status = 'superseded'
   WHERE user_id = NEW.user_id AND status = 'active' AND source = 'user_stated'
     AND field_key IN ('preferred_name','what_role_should_ai_play','how_direct_should_ai_be',
                       'topics_they_enjoy_discussing','topics_they_do_not_want_discussed');
  INSERT INTO public.mind_facts(user_id, field_key, group_id, attribute_name, value, source, sensitivity_level, expiration_policy)
  SELECT NEW.user_id, k, 1, a, v, 'user_stated', 'L1', 'review_12_months'
  FROM (VALUES
    ('preferred_name', 'Preferred name', NULLIF(NEW.display_name, '')),
    ('what_role_should_ai_play', 'Role Mini should play', NULLIF(NEW.companion_mode, '')),
    ('how_direct_should_ai_be', 'How direct Mini should be', NULLIF(NEW.tone, '')),
    ('topics_they_enjoy_discussing', 'On their mind lately', NULLIF(NEW.focus, '')),
    ('topics_they_do_not_want_discussed', 'Topics to avoid', NULLIF(NEW.boundaries, ''))
  ) AS x(k, a, v) WHERE v IS NOT NULL;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS mind_sync_from_profile ON public.mini_profiles;
CREATE TRIGGER mind_sync_from_profile AFTER INSERT OR UPDATE OF display_name, birth_year, companion_mode, tone, focus, boundaries
  ON public.mini_profiles FOR EACH ROW EXECUTE FUNCTION public.mind_sync_from_profile();

-- ============================================================ sync score ("Mini knows you N%")
-- 60% = coverage of the person's life-stage focus fields, 40% = breadth across the 30 groups.
-- Only consented, active, user-stated/confirmed facts count (AI guesses don't).
CREATE OR REPLACE FUNCTION public.mind_sync_score()
RETURNS jsonb LANGUAGE sql STABLE SECURITY INVOKER SET search_path = '' AS $$
  WITH me AS (
    SELECT p.user_id, public.mind_stage_for_age(extract(year FROM now())::int - p.birth_year) AS stage
    FROM public.mind_persons p WHERE p.user_id = (select auth.uid())
  ), known AS (
    SELECT DISTINCT f.field_key, f.group_id FROM public.mind_facts f, me
    WHERE f.user_id = me.user_id AND f.status = 'active' AND f.consent_status = 'granted'
      AND f.source IN ('user_stated','user_confirmed','imported')
  ), core AS (
    SELECT DISTINCT unnest(sf.field_keys) AS field_key FROM public.mind_stage_focus sf, me
    WHERE sf.stage = me.stage AND NOT sf.only_if_user_raises
  ), parts AS (
    SELECT (SELECT count(*) FROM core) AS core_total,
           (SELECT count(*) FROM core JOIN known USING (field_key)) AS core_known,
           (SELECT count(DISTINCT group_id) FROM known) AS groups_known
  )
  SELECT jsonb_build_object(
    'stage', (SELECT stage FROM me),
    'score', round(60 * CASE WHEN core_total = 0 THEN 0 ELSE core_known::numeric / core_total END
                   + 40 * groups_known::numeric / 30),
    'core_known', core_known, 'core_total', core_total, 'groups_known', groups_known)
  FROM parts
$$;

-- ============================================================ context package (sec 9)
-- What Mini gets before a conversation: a SMALL, relevant, permission-filtered
-- package — never the whole database. Runs as the person (RLS applies).
CREATE OR REPLACE FUNCTION public.mind_context_package(p_agent text DEFAULT 'mini', p_purpose text DEFAULT 'companion_conversation')
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  me public.mind_persons%ROWTYPE; st public.mind_life_stages%ROWTYPE;
  lvl text := 'L2'; perm public.mind_agent_permissions%ROWTYPE; age int; pkg jsonb;
BEGIN
  SELECT * INTO me FROM public.mind_persons WHERE user_id = (select auth.uid());
  IF NOT FOUND THEN RETURN jsonb_build_object('known', false); END IF;
  age := extract(year FROM now())::int - me.birth_year;
  IF age IS NULL OR age < 18 THEN RETURN jsonb_build_object('known', false, 'reason', 'adults_only'); END IF;
  SELECT * INTO st FROM public.mind_life_stages WHERE stage = public.mind_stage_for_age(age);
  SELECT * INTO perm FROM public.mind_agent_permissions
   WHERE user_id = me.user_id AND agent = p_agent AND purpose = p_purpose AND revoked_at IS NULL
     AND (expires_at IS NULL OR expires_at > now());
  IF FOUND THEN lvl := perm.max_level; END IF;

  pkg := jsonb_build_object(
    'known', true,
    'name', me.preferred_name,
    'age', age,
    'stage', jsonb_build_object('stage', st.stage, 'title', st.title, 'theme', st.theme, 'persona', st.persona),
    'conversations', me.conversations,
    'last_talk_at', me.last_talk_at,
    'facts', coalesce((
      SELECT jsonb_agg(jsonb_build_object('group', f.group_id, 'what', f.attribute_name, 'value', f.value,
                                          'since', f.valid_from::date, 'needs_reconfirm', f.review_at < now()))
      FROM (SELECT * FROM public.mind_facts f
            WHERE f.user_id = me.user_id AND f.status = 'active' AND f.consent_status = 'granted'
              AND f.sensitivity_level <= lvl AND p_agent = ANY(f.permitted_ai_agents)
              AND (perm.group_ids IS NULL OR f.group_id = ANY(perm.group_ids))
              AND (f.valid_until IS NULL OR f.valid_until > now())
            ORDER BY (f.group_id = 30) DESC, f.updated_at DESC LIMIT 25) f), '[]'::jsonb),
    'avoid_topics', coalesce((
      SELECT jsonb_agg(f.value) FROM public.mind_facts f
      WHERE f.user_id = me.user_id AND f.status = 'active' AND f.consent_status = 'granted'
        AND f.field_key IN ('topics_they_do_not_want_discussed','topics_they_find_uncomfortable',
                            'experiences_they_do_not_want_ai_to_revisit','what_should_ai_never_do')), '[]'::jsonb),
    'recent_days', coalesce((
      SELECT jsonb_agg(jsonb_build_object('on', e.occurred_on, 'title', e.title, 'emotion', e.emotion))
      FROM (SELECT * FROM public.mind_life_events e
            WHERE e.user_id = me.user_id AND e.consent_status = 'granted' AND NOT e.never_revisit
              AND e.occurred_on >= current_date - 14
            ORDER BY e.occurred_on DESC, e.importance DESC LIMIT 6) e), '[]'::jsonb),
    'follow_ups', coalesce((
      SELECT jsonb_agg(jsonb_build_object('id', e.id, 'ask', e.follow_up_question, 'about', e.title))
      FROM (SELECT * FROM public.mind_life_events e
            WHERE e.user_id = me.user_id AND e.followed_up_at IS NULL AND e.follow_up_at <= now()
              AND e.consent_status = 'granted' AND NOT e.never_revisit
            ORDER BY e.follow_up_at LIMIT 2) e), '[]'::jsonb),
    'people', coalesce((
      SELECT jsonb_agg(jsonb_build_object('name', p.name, 'relation', p.relation))
      FROM (SELECT * FROM public.mind_people p
            WHERE p.user_id = me.user_id AND p.consent_status = 'granted' AND NOT p.avoid
            ORDER BY p.closeness DESC NULLS LAST, p.last_mentioned_at DESC NULLS LAST LIMIT 8) p), '[]'::jsonb),
    'goals', coalesce((
      SELECT jsonb_agg(jsonb_build_object('title', g.title, 'progress', g.progress, 'target', g.target_date))
      FROM (SELECT * FROM public.mind_goals g
            WHERE g.user_id = me.user_id AND g.status = 'active' AND g.consent_status = 'granted'
            ORDER BY g.priority DESC, g.updated_at DESC LIMIT 4) g), '[]'::jsonb),
    'insights', coalesce((
      SELECT jsonb_agg(jsonb_build_object('layer', i.layer, 'note', i.statement, 'confidence', i.confidence))
      FROM (SELECT * FROM public.mind_insights i
            WHERE i.user_id = me.user_id AND i.status IN ('open','accepted') AND i.expires_at > now()
            ORDER BY i.confidence DESC LIMIT 3) i), '[]'::jsonb),
    'next_question', (
      SELECT jsonb_build_object('focus_id', sf.id, 'topic', sf.item, 'ask', q.question)
      FROM public.mind_stage_focus sf CROSS JOIN LATERAL unnest(sf.questions) WITH ORDINALITY AS q(question, n)
      WHERE sf.stage = st.stage AND NOT sf.only_if_user_raises
        AND (NOT sf.sensitive OR me.conversations >= 5)        -- sensitive topics only after trust
        AND NOT EXISTS (SELECT 1 FROM public.mind_questions_asked a
                        WHERE a.user_id = me.user_id AND a.focus_id = sf.id AND a.question = q.question)
        AND NOT EXISTS (SELECT 1 FROM public.mind_facts f WHERE f.user_id = me.user_id AND f.status = 'active'
                        AND f.consent_status = 'granted' AND f.field_key = ANY(sf.field_keys))
      ORDER BY sf.sensitive, sf.ord, q.n LIMIT 1),
    'sync', public.mind_sync_score()
  );
  RETURN pkg;
END $$;

REVOKE ALL ON FUNCTION public.mind_context_package(text, text) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.mind_context_package(text, text) TO authenticated;
REVOKE ALL ON FUNCTION public.mind_sync_score() FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.mind_sync_score() TO authenticated;

-- ============================================================ semantic memory (pgvector, optional)
-- Enabled where the extension exists (Supabase): embeddings for meaning-based recall.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'vector') THEN
    CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;
    EXECUTE 'ALTER TABLE public.mind_facts ADD COLUMN IF NOT EXISTS embedding extensions.vector(768)';
    EXECUTE 'ALTER TABLE public.mind_life_events ADD COLUMN IF NOT EXISTS embedding extensions.vector(768)';
    EXECUTE 'CREATE INDEX IF NOT EXISTS mind_facts_embedding_idx ON public.mind_facts USING hnsw (embedding extensions.vector_cosine_ops)';
    EXECUTE 'CREATE INDEX IF NOT EXISTS mind_events_embedding_idx ON public.mind_life_events USING hnsw (embedding extensions.vector_cosine_ops)';
  END IF;
END $$;
