# Architecture

```text
Browser /u/{slug}
        |
        | tenant PIN
        v
  Mini AI service -------------------- OpenAI-compatible LLM
        |
        +-- registry.sqlite3 (scrypt PIN hashes only)
        +-- tenants/{slug}.sqlite3 (isolated chat history)
        |
        | authenticated Streamable HTTP MCP
        v
  Vault Zeta /mcp/ ------------------- shared pgvector memory
        ^
        |
  Claude / ChatGPT / Cursor / custom MCP agent
```

## Boundaries

Mini owns tenant onboarding, tenant authentication, local conversation history, the companion prompt, and the browser experience. Vault Zeta owns model-neutral durable memory, retrieval, provenance, secret rejection, and cross-agent continuity.

Voiceprints and raw audio are intentionally outside this hosted boundary. Those experiments remain device-local; the Railway service does not collect or persist biometric voice features.

The integration is deliberately asymmetric:

- local Mini history is always tenant-isolated;
- Vault reads happen only for tenants explicitly created with `vault_enabled=true`;
- Vault writes happen only after an explicit remember request;
- admin bridge endpoints make integration testing possible without enabling any tenant.

This avoids treating a shared memory database as a multi-tenant authorization system. Vault Zeta's current MCP surface is one configured user's memory, so it must never be silently shared with every Mini tenant.

## Failure behavior

Liveness never depends on the LLM or Vault. Readiness can require them in production. A Vault recall failure does not block an ordinary chat, but an explicit remember action fails clearly rather than pretending the memory was saved.
