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
