#!/usr/bin/env bash
# Apply every Supabase migration to a THROWAWAY Postgres 16 cluster (with
# minimal Supabase auth stubs) and run supabase/tests/*.sql.
# Touches nothing else: own data dir, own port, own socket; removed at the end.
# Usage (as root on a host with postgresql-16 binaries): scripts/mind/run_db_tests.sh
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
BIN=${PG_BIN:-/usr/lib/postgresql/16/bin}
DIR=${PG_TEST_DIR:-/var/lib/postgresql/mini-mind-test}
PORT=${PG_TEST_PORT:-5499}
as_pg() { runuser -u postgres -- "$@"; }
cleanup() { as_pg "$BIN/pg_ctl" -D "$DIR/data" stop -m fast >/dev/null 2>&1 || true; rm -rf "$DIR"; }
cleanup; trap cleanup EXIT
mkdir -p "$DIR"; chown postgres:postgres "$DIR"; cd /tmp
as_pg "$BIN/initdb" -D "$DIR/data" -A trust -U postgres >/dev/null
as_pg "$BIN/pg_ctl" -D "$DIR/data" -o "-p $PORT -k $DIR -c listen_addresses=''" -l "$DIR/log" start >/dev/null
sleep 2
run() { cp "$1" "$DIR/run.sql"; chown postgres "$DIR/run.sql"; as_pg psql -h "$DIR" -p "$PORT" -U postgres -d postgres -v ON_ERROR_STOP=1 -q -f "$DIR/run.sql"; }
cat > "$DIR/stubs.sql" <<'SQL'
CREATE ROLE anon NOLOGIN; CREATE ROLE authenticated NOLOGIN; CREATE ROLE service_role NOLOGIN BYPASSRLS;
CREATE SCHEMA auth; CREATE SCHEMA extensions;
CREATE TABLE auth.users (id uuid PRIMARY KEY, email text);
CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS $$ SELECT nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
CREATE FUNCTION public.rls_auto_enable() RETURNS void LANGUAGE sql AS $$ SELECT $$;
GRANT USAGE ON SCHEMA auth, public TO anon, authenticated; GRANT EXECUTE ON FUNCTION auth.uid() TO anon, authenticated;
SQL
run "$DIR/stubs.sql"
for f in $(ls "$ROOT"/supabase/migrations/*.sql | sort); do echo "migrate $(basename "$f")"; run "$f"; done
for f in "$ROOT"/supabase/tests/*.sql; do echo "test    $(basename "$f")"; cp "$f" "$DIR/run.sql"; chown postgres "$DIR/run.sql"
  as_pg psql -h "$DIR" -p "$PORT" -U postgres -d postgres -v ON_ERROR_STOP=1 -q -o /dev/null -f "$DIR/run.sql" 2>&1 | sed -E 's/^psql:[^ ]+ NOTICE:  /  /'
  test "${PIPESTATUS[0]}" -eq 0; done
echo "ALL DATABASE TESTS PASSED"
