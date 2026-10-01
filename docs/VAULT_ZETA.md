# Vault Zeta MCP integration

Mini is an MCP client. It calls the production Vault tools instead of importing Vault's database or embedding implementation:

- `vault_memory_stats`
- `vault_memory_context`
- `vault_memory_search`
- `vault_memory_remember`

The MCP URL must retain its trailing slash. Authentication is `Authorization: Bearer <VAULT_API_KEY>`.

For Railway private networking, use the Vault service's private domain and port. Add that private hostname to Vault's `MCP_ALLOWED_HOSTS`; Vault's DNS-rebinding protection will otherwise correctly reject an unexpected host.

Mini writes provenance labels such as `mini-ai-admin` and `mini-ai.<tenant-slug>`. Vault normalizes these into `mcp:<label>` source metadata.

Never put tenant PINs, model keys, Vault keys, session cookies, or other credentials into durable memory. Vault also rejects recognized credential-shaped writes server-side.

