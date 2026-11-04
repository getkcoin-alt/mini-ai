# Mini AI

Mini AI is a private, multi-tenant companion service with optional shared continuity through Vault Zeta.

It preserves the design already used by the original Mini implementation:

- one shared deployment;
- admin-created personal links at `/u/{slug}`;
- a separate PIN and SQLite database for every tenant;
- Best Friend and Mentor modes;
- explicit, opt-in access to the operator's Vault Zeta memory.

The hosted service is intentionally text-first. The earlier device-local voiceprint and offline audio experiments stay device-local instead of moving biometric data into this public cloud service.

Vault Zeta remains a separate service. Mini connects to its authenticated Streamable HTTP MCP endpoint and uses the same `vault_memory_*` tools as other AI agents. Mini does not create a second copy of shared memory.

## Security boundary

New tenants have `vault_enabled=false`. Their local messages never enter Vault Zeta. Enabling Vault for a tenant allows relevant shared continuity to be read during chat and allows an explicit **Remember in Vault Zeta** action. This must only be enabled for a person who is meant to share the operator's Vault.

- Tenant PINs are stored as salted scrypt hashes.
- PINs are sent in an authorization header, never in the URL.
- Every tenant has its own SQLite file.
- Admin and Vault bridge routes require `MINI_ADMIN_API_KEY`.
- Vault credentials and model credentials are environment variables only.
- Vault rejects credential-shaped durable memories.
- Recalled memory is treated as untrusted data, not instructions or authority.

## Local development

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
cp .env.example .env
pytest -q
uvicorn miniai.app:app --reload
```

Create a tenant:

```bash
curl -X POST http://127.0.0.1:8000/v1/mini/admin/onboard \
  -H "Authorization: Bearer $MINI_ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"owner_name":"Karnveer","vault_enabled":true}'
```

The PIN is returned once in the onboarding response. Open the returned URL and enter it.

## Railway deployment

The repository contains a Dockerfile plus the current Railway Infrastructure-as-Code partial in `.railway/railway.ts`. It connects this repository and branch to the `mini-ai` service, uses `/health/live` as the platform health check, and mounts a 1 GB persistent volume at `/data`. The service listens on Railway's injected `PORT`; set `MINI_DATA_DIR=/data`.

Recommended private-network variables when Mini and Vault Zeta are in the same Railway project:

```text
APP_ENV=production
MINI_DATA_DIR=/data
MINI_ADMIN_API_KEY=<random secret>
LLM_BASE_URL=${{api.LLM_BASE_URL}}
LLM_API_KEY=${{api.LLM_API_KEY}}
LLM_MODEL=${{api.LLM_MODEL}}
LLM_REQUIRED=true
VAULT_MCP_URL=http://${{api.RAILWAY_PRIVATE_DOMAIN}}:${{api.PORT}}/mcp/
VAULT_API_KEY=${{api.VAULT_API_KEY}}
VAULT_MCP_REQUIRED=true
```

The Vault API must allow its Railway private hostname in `MCP_ALLOWED_HOSTS`.

## Health contract

- `GET /health/live` proves the process and event loop are serving. It never calls the model or Vault.
- `GET /health/ready` checks local storage and, when required, verifies the model provider's authenticated `/models` endpoint and performs `vault_memory_stats` through MCP.
- `GET /v1/status` exposes only configuration booleans, never secret values.

## Proving cross-agent memory

Use a unique canary rather than asking a generic question.

1. Through Mini's protected bridge, call `POST /v1/vault/remember` with a phrase such as `ZETA-CANARY-MINI-2026: blue banyan orbit 7319`.
2. In another MCP-capable AI, connect to `https://<vault-host>/mcp/` with the Vault bearer key.
3. Ask that agent to call `vault_memory_search` for `ZETA-CANARY-MINI-2026` and return content and provenance. The source will identify Mini.
4. Have that agent call `vault_memory_remember` with a second unique phrase.
5. Call Mini's `POST /v1/vault/search` for the second phrase.

Both directions must return the exact canary. A successful connection alone is not proof that both agents use the same store.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/VAULT_ZETA.md](docs/VAULT_ZETA.md).


## Personal companion pilot

The browser now includes a first-visit preferences form, personal memory notebook,
and one active Mentor goal with progress check-ins. Existing tenant databases are
upgraded lazily using additive `CREATE TABLE IF NOT EXISTS`; existing chats and PINs
are retained. Back up `/data` before rollout.

Personal memory is **off by default**, separate from Vault Zeta. A person can opt in,
save notes explicitly (or save their next message), edit and delete notes, and pause
recall without deleting saved notes. Mini retrieves up to eight personal notes using
word overlap and recent updates; this is bounded lexical recall, not semantic search
or unlimited recall of the entire chat history. No automatic extraction is performed.
The active goal and latest five check-ins are provided in Mentor mode. Focus and tone
preferences guide both modes even when personal memory recall is paused.

New authenticated routes under `/v1/mini/t/{slug}`:

- `PUT /preferences`: tone, focus, preferred mode, personal-memory consent.
- `GET/POST /memories`, `PUT/DELETE /memories/{id}`: private notebook (200 notes max).
- `GET/POST /goals`, `POST /goals/{id}/checkins`: one active goal and progress.
- `GET /export`: all Mini messages, preferences, memories and goals as JSON.
- `PUT /pin`: replace the current PIN with 6–12 digits; the old PIN stops working.
- `POST /erase`: requires `{"confirmation":"DELETE MY MINI DATA"}`. Removes the
  tenant database, its WAL/SHM files, and name/PIN from the registry. Keeps the slug
  as a disabled tombstone so an old personal link is never reassigned. Does not
  remove operator backups, AI-provider logs, or separately shared Vault records.

Admin-assisted recovery: `POST /v1/mini/admin/tenants/{slug}/reset-pin` with the
admin bearer key returns a new six-digit PIN once. Verify the person's identity
before resetting or sharing a new PIN. No email identity or self-service recovery
is claimed. The earlier admin DELETE endpoint still **deactivates**, not erases.

Pilot controls are per-process: 10 incorrect PIN attempts lock a personal link for
five minutes; additional per-link/address request ceilings bound hashing work.
Authenticated chat budgets default to 20/minute and 200/day per person, configurable
through `MINI_CHAT_PER_MINUTE` / `MINI_CHAT_PER_DAY`. Requests for each active tenant
are serialized so an erase cannot race an in-flight chat and recreate their data.
Run one process/replica (as configured); counters reset on restart. Before scaling,
replace in-memory locks/limits with shared coordination, and add platform-level
abuse protection. HTTP forwarding headers are not trusted for limiter identity.

Chat failures restore the user's draft. Shared Vault writes happen only after a
successful model response; an unavailable explicit save is reported as an error.
Personal notes never enter Vault automatically. Vault-enabled users see a separately
labelled checkbox explaining that those writes go to the operator's shared Vault.

Tests use fake model/Vault clients: they verify isolation, consent, recall, progress,
exports, recovery, erasure, failed-generation handling and quotas. A real model and
Vault smoke test is still required in the deployment environment before public use.
