def _onboard(client, headers, name, *, vault_enabled=False):
    response = client.post(
        "/v1/mini/admin/onboard",
        headers=headers,
        json={"owner_name": name, "vault_enabled": vault_enabled},
    )
    assert response.status_code == 200
    return response.json()


def test_onboarding_pin_auth_and_isolation(app_client, admin_headers):
    client, _, llm = app_client
    one = _onboard(client, admin_headers, "Asha")
    two = _onboard(client, admin_headers, "Asha")

    assert one["slug"] == "asha"
    assert two["slug"] == "asha-2"
    assert one["pin"] != two["pin"]

    assert client.get(f"/v1/mini/t/{one['slug']}/profile").status_code == 401
    assert client.get(
        f"/v1/mini/t/{one['slug']}/profile", headers={"Authorization": "Bearer 0000"}
    ).status_code == 401

    auth = {"Authorization": f"Bearer {one['pin']}"}
    profile = client.get(f"/v1/mini/t/{one['slug']}/profile", headers=auth)
    assert profile.status_code == 200
    assert profile.json()["owner_name"] == "Asha"

    chat = client.post(
        f"/v1/mini/t/{one['slug']}/chat",
        headers=auth,
        json={"message": "Hello Mini", "mode": "friend"},
    )
    assert chat.status_code == 200
    assert chat.json()["reply"] == "Mini heard: Hello Mini"
    assert llm.calls[-1]["vault_context"] == ""

    history = client.get(f"/v1/mini/t/{one['slug']}/history", headers=auth).json()
    assert [row["role"] for row in history["messages"]] == ["user", "assistant"]

    auth_two = {"Authorization": f"Bearer {two['pin']}"}
    assert client.get(
        f"/v1/mini/t/{two['slug']}/history", headers=auth_two
    ).json()["count"] == 0


def test_deactivate_tenant(app_client, admin_headers):
    client, _, _ = app_client
    tenant = _onboard(client, admin_headers, "Riya")
    response = client.delete(
        f"/v1/mini/admin/tenants/{tenant['slug']}", headers=admin_headers
    )
    assert response.status_code == 200
    assert client.get(
        f"/v1/mini/t/{tenant['slug']}/profile",
        headers={"Authorization": f"Bearer {tenant['pin']}"},
    ).status_code == 401

