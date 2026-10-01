def test_admin_vault_bridge(app_client, admin_headers):
    client, vault, _ = app_client
    status = client.get("/v1/vault/status", headers=admin_headers)
    assert status.status_code == 200
    assert status.json()["user"] == "karnveer"

    search = client.post(
        "/v1/vault/search", headers=admin_headers, json={"query": "project decision"}
    )
    assert search.status_code == 200
    assert search.json()["query"] == "project decision"

    remembered = client.post(
        "/v1/vault/remember",
        headers=admin_headers,
        json={"content": "A durable cross-agent fact", "kind": "factual", "importance": 0.8},
    )
    assert remembered.status_code == 200
    assert vault.remembered[-1]["client"] == "mini-ai-admin"


def test_vault_enabled_tenant_recalls_and_explicitly_remembers(app_client, admin_headers):
    client, vault, llm = app_client
    tenant = client.post(
        "/v1/mini/admin/onboard",
        headers=admin_headers,
        json={"owner_name": "Karnveer", "vault_enabled": True},
    ).json()
    auth = {"Authorization": f"Bearer {tenant['pin']}"}

    response = client.post(
        f"/v1/mini/t/{tenant['slug']}/chat",
        headers=auth,
        json={"message": "Remember my verification phrase", "remember": True},
    )
    assert response.status_code == 200
    assert response.json()["vault_context_used"] is True
    assert response.json()["vault_memory"]["stored"] is True
    assert "<vault_memories>" in llm.calls[-1]["vault_context"]
    assert vault.remembered[-1]["client"] == "mini-ai.karnveer"


def test_tenant_without_vault_cannot_write_shared_memory(app_client, admin_headers):
    client, _, _ = app_client
    tenant = client.post(
        "/v1/mini/admin/onboard",
        headers=admin_headers,
        json={"owner_name": "Private Tenant", "vault_enabled": False},
    ).json()
    response = client.post(
        f"/v1/mini/t/{tenant['slug']}/chat",
        headers={"Authorization": f"Bearer {tenant['pin']}"},
        json={"message": "Do not share this", "remember": True},
    )
    assert response.status_code == 403

