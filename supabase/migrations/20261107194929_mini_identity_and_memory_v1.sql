-- Migration applied on 2026-11-07 to Miniai Supabase project.
-- This is the authoritative, versioned definition of the first consented
-- per-user profile, memory, conversation and message tables.
-- Do NOT run manually on an unrelated Supabase project.

REVOKE ALL ON FUNCTION public.rls_auto_enable() FROM PUBLIC, anon, authenticated;

CREATE TABLE IF NOT EXISTS public.mini_profiles (
 user_id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
 display_name text NOT NULL DEFAULT '' CHECK (char_length(display_name) <= 80),
 mini_name text NOT NULL DEFAULT 'Mini' CHECK (char_length(mini_name) BETWEEN 1 AND 80),
 companion_mode text NOT NULL DEFAULT 'both' CHECK (companion_mode IN ('friend','mentor','both')),
 tone text NOT NULL DEFAULT 'balanced' CHECK (tone IN ('gentle','balanced','direct')),
 focus text NOT NULL DEFAULT '' CHECK (char_length(focus) <= 600),
 boundaries text NOT NULL DEFAULT '' CHECK (char_length(boundaries) <= 600),
 consented_at timestamptz NOT NULL,
 updated_at timestamptz NOT NULL DEFAULT now(),
 created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.mini_memories (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
 kind text NOT NULL DEFAULT 'preference' CHECK (kind IN ('preference','goal','project','fact')),
 content text NOT NULL CHECK (char_length(content) BETWEEN 1 AND 1600),
 confirmed_at timestamptz NOT NULL,
 expires_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 CHECK (expires_at IS NULL OR expires_at > created_at)
);
CREATE INDEX IF NOT EXISTS mini_memories_owner_recent_idx ON public.mini_memories(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.mini_conversations (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
 title text NOT NULL DEFAULT 'New conversation' CHECK (char_length(title) BETWEEN 1 AND 120),
 history_consented_at timestamptz NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE (id,user_id)
);
CREATE INDEX IF NOT EXISTS mini_conversations_owner_idx ON public.mini_conversations(user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS public.mini_messages (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 conversation_id uuid NOT NULL,
 user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
 role text NOT NULL CHECK (role IN ('user','assistant')),
 body text NOT NULL CHECK (char_length(body) BETWEEN 1 AND 4000),
 heard_by_user boolean NOT NULL DEFAULT false,
 created_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT mini_messages_owner_conversation_fk
  FOREIGN KEY (conversation_id,user_id) REFERENCES public.mini_conversations(id,user_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS mini_messages_owner_conversation_idx
 ON public.mini_messages(user_id,conversation_id,created_at);

ALTER TABLE public.mini_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.mini_memories ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.mini_conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.mini_messages ENABLE ROW LEVEL SECURITY;

CREATE POLICY mini_profiles_read_own ON public.mini_profiles
 FOR SELECT TO authenticated USING ((select auth.uid()) = user_id);
CREATE POLICY mini_profiles_insert_own ON public.mini_profiles
 FOR INSERT TO authenticated WITH CHECK ((select auth.uid()) = user_id AND consented_at IS NOT NULL);
CREATE POLICY mini_profiles_update_own ON public.mini_profiles
 FOR UPDATE TO authenticated USING ((select auth.uid()) = user_id)
 WITH CHECK ((select auth.uid()) = user_id AND consented_at IS NOT NULL);
CREATE POLICY mini_profiles_delete_own ON public.mini_profiles
 FOR DELETE TO authenticated USING ((select auth.uid()) = user_id);

CREATE POLICY mini_memories_read_own ON public.mini_memories
 FOR SELECT TO authenticated USING ((select auth.uid()) = user_id);
CREATE POLICY mini_memories_insert_own ON public.mini_memories
 FOR INSERT TO authenticated WITH CHECK ((select auth.uid()) = user_id AND confirmed_at IS NOT NULL);
CREATE POLICY mini_memories_update_own ON public.mini_memories
 FOR UPDATE TO authenticated USING ((select auth.uid()) = user_id)
 WITH CHECK ((select auth.uid()) = user_id AND confirmed_at IS NOT NULL);
CREATE POLICY mini_memories_delete_own ON public.mini_memories
 FOR DELETE TO authenticated USING ((select auth.uid()) = user_id);

CREATE POLICY mini_conversations_read_own ON public.mini_conversations
 FOR SELECT TO authenticated USING ((select auth.uid()) = user_id);
CREATE POLICY mini_conversations_insert_own ON public.mini_conversations
 FOR INSERT TO authenticated WITH CHECK ((select auth.uid()) = user_id AND history_consented_at IS NOT NULL);
CREATE POLICY mini_conversations_update_own ON public.mini_conversations
 FOR UPDATE TO authenticated USING ((select auth.uid()) = user_id)
 WITH CHECK ((select auth.uid()) = user_id AND history_consented_at IS NOT NULL);
CREATE POLICY mini_conversations_delete_own ON public.mini_conversations
 FOR DELETE TO authenticated USING ((select auth.uid()) = user_id);

CREATE POLICY mini_messages_read_own ON public.mini_messages
 FOR SELECT TO authenticated USING ((select auth.uid()) = user_id);
CREATE POLICY mini_messages_insert_own ON public.mini_messages
 FOR INSERT TO authenticated WITH CHECK ((select auth.uid()) = user_id);
CREATE POLICY mini_messages_update_own ON public.mini_messages
 FOR UPDATE TO authenticated USING ((select auth.uid()) = user_id)
 WITH CHECK ((select auth.uid()) = user_id);
CREATE POLICY mini_messages_delete_own ON public.mini_messages
 FOR DELETE TO authenticated USING ((select auth.uid()) = user_id);

REVOKE ALL ON TABLE public.mini_profiles, public.mini_memories,
 public.mini_conversations, public.mini_messages FROM PUBLIC, anon;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE
 public.mini_profiles, public.mini_memories, public.mini_conversations, public.mini_messages
 TO authenticated, service_role;
