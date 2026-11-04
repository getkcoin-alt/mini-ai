import json


def user(client, admin, name):
    row = client.post("/v1/mini/admin/onboard", headers=admin, json={"owner_name": name}).json()
    return f"/v1/mini/t/{row['slug']}", {"Authorization": f"Bearer {row['pin']}"}


def preferences(client, root, auth, enabled=True):
    response = client.put(
        root + "/preferences",
        headers=auth,
        json={
            "tone": "direct",
            "focus": "Learn English",
            "mode": "mentor",
            "memory_enabled": enabled,
        },
    )
    assert response.status_code == 200
    return response.json()


def test_memory_consent_recall_isolation_edit_delete(app_client, admin_headers):
    client, vault, llm = app_client
    one, auth = user(client, admin_headers, "One")
    two, other = user(client, admin_headers, "Two")
    assert (
        client.post(
            one + "/memories", headers=auth, json={"content": "I practice English at 8pm"}
        ).status_code
        == 403
    )
    preferences(client, one, auth)
    saved = client.post(
        one + "/memories", headers=auth, json={"content": "I practice English at 8pm"}
    ).json()
    assert client.get(two + "/memories", headers=other).json()["memories"] == []
    assert client.get(one + "/memories", headers=other).status_code == 401
    preferences(client, two, other)
    assert (
        client.put(
            two + "/memories/" + saved["id"], headers=other, json={"content": "stolen"}
        ).status_code
        == 404
    )
    assert client.delete(two + "/memories/" + saved["id"], headers=other).status_code == 404
    client.post(one + "/chat", headers=auth, json={"message": "English practice?"})
    assert "8pm" in llm.calls[-1]["personal_context"]
    assert vault.remembered == []
    assert (
        client.put(
            one + "/memories/" + saved["id"],
            headers=auth,
            json={"content": "I practice English at 9pm"},
        ).status_code
        == 200
    )
    preferences(client, one, auth, False)
    client.post(one + "/chat", headers=auth, json={"message": "English practice?"})
    assert json.loads(llm.calls[-1]["personal_context"])["personal_memories"] == []
    assert client.delete(one + "/memories/" + saved["id"], headers=auth).status_code == 200
    assert client.get(one + "/memories", headers=auth).json()["memories"] == []


def test_mentor_progress_and_cross_user_boundary(app_client, admin_headers):
    client, _, llm = app_client
    root, auth = user(client, admin_headers, "Mentor")
    other, other_auth = user(client, admin_headers, "Other")
    goal = client.post(
        root + "/goals",
        headers=auth,
        json={"title": "Speak English", "next_step": "Practice 10 minutes"},
    ).json()
    assert (
        client.post(
            root + "/goals", headers=auth, json={"title": "Second", "next_step": "No"}
        ).status_code
        == 409
    )
    path = "/goals/" + goal["id"] + "/checkins"
    data = {"note": "Practiced today", "next_step": "Practice tomorrow", "complete": False}
    assert client.post(other + path, headers=other_auth, json=data).status_code == 404
    assert client.post(root + path, headers=auth, json=data).status_code == 200
    client.post(root + "/chat", headers=auth, json={"message": "What next?", "mode": "mentor"})
    context = json.loads(llm.calls[-1]["personal_context"])
    assert context["active_goals"][0]["checkins"][0]["note"] == "Practiced today"
    client.post(root + path, headers=auth, json={**data, "complete": True})
    client.post(root + "/chat", headers=auth, json={"message": "What next?", "mode": "mentor"})
    assert json.loads(llm.calls[-1]["personal_context"])["active_goals"] == []


def test_export_pin_recovery_and_erasure(app_client, admin_headers):
    client, _, _ = app_client
    root, auth = user(client, admin_headers, "Export")
    preferences(client, root, auth)
    client.post(
        root + "/chat",
        headers=auth,
        json={"message": "Remember my English goal", "remember_private": True},
    )
    exported = client.get(root + "/export", headers=auth).json()
    assert len(exported["messages"]) == 2
    assert len(exported["memories"]) == 1
    assert "pin" not in json.dumps(exported)
    assert client.put(root + "/pin", headers=auth, json={"pin": "123456"}).status_code == 200
    assert client.get(root + "/profile", headers=auth).status_code == 401
    recovered = client.post("/v1/mini/admin/tenants/export/reset-pin", headers=admin_headers).json()
    auth = {"Authorization": "Bearer " + recovered["pin"]}
    assert client.get(root + "/profile", headers=auth).status_code == 200
    assert (
        client.post(root + "/erase", headers=auth, json={"confirmation": "wrong"}).status_code
        == 422
    )
    assert (
        client.post(
            root + "/erase", headers=auth, json={"confirmation": "DELETE MY MINI DATA"}
        ).status_code
        == 200
    )
    assert client.get(root + "/export", headers=auth).status_code == 401
    store = client.app.state.store
    assert not store._tenant_path("export").exists()
    row = store.get("export", include_inactive=True)
    assert row.owner_name == "" and row.pin_hash == "" and not row.active
    new, _ = user(client, admin_headers, "Export")
    assert new.endswith("export-2")


def test_failure_does_not_save_private_memory(app_client, admin_headers):
    client, _, llm = app_client
    root, auth = user(client, admin_headers, "Failure")
    preferences(client, root, auth)
    from miniai.llm import LLMUnavailable

    async def failed(**kwargs):
        raise LLMUnavailable("Offline")

    llm.reply = failed
    response = client.post(
        root + "/chat", headers=auth, json={"message": "Save this", "remember_private": True}
    )
    assert response.status_code == 503
    assert client.get(root + "/memories", headers=auth).json()["memories"] == []
    assert client.get(root + "/history", headers=auth).json()["messages"] == []


def test_pin_lockout_and_chat_budget(app_client, admin_headers):
    client, _, _ = app_client
    root, auth = user(client, admin_headers, "Limits")
    for _ in range(10):
        assert (
            client.get(root + "/profile", headers={"Authorization": "Bearer wrong"}).status_code
            == 401
        )
    assert client.get(root + "/profile", headers=auth).status_code == 429
    root, auth = user(client, admin_headers, "Chat budget")
    for _ in range(20):
        assert (
            client.post(root + "/chat", headers=auth, json={"message": "Hello"}).status_code == 200
        )
    assert client.post(root + "/chat", headers=auth, json={"message": "Hello"}).status_code == 429


def test_existing_history_survives_additive_upgrade(tmp_path):
    import sqlite3

    from miniai.store import TenantStore

    store = TenantStore(tmp_path)
    tenant, _ = store.onboard("Existing")
    path = store._tenant_path(tenant.slug)
    with sqlite3.connect(path) as conn:
        for table in ("checkins", "goals", "memories", "preferences"):
            conn.execute("DROP TABLE " + table)
        conn.execute(
            "INSERT INTO messages VALUES ('old', 'user', 'Original history', '2026-01-01')"
        )
    assert store.preferences(tenant.slug)["memory_enabled"] is False
    assert store.history(tenant.slug)[0]["content"] == "Original history"
    saved = store.save_memory(tenant.slug, "English practice at 8pm")
    store.save_memory(tenant.slug, "I enjoy gardening")
    assert store.recall(tenant.slug, "English")[0]["id"] == saved["id"]


def test_erase_waits_for_chat_and_does_not_recreate_data(tmp_path):
    import asyncio

    import httpx

    from miniai.app import create_app
    from miniai.config import Settings

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        class DelayedLLM:
            configured = True

            async def reply(self, **kwargs):
                entered.set()
                await release.wait()
                return "Done"

        app = create_app(Settings(mini_data_dir=tmp_path), llm=DelayedLLM())
        tenant, pin = app.state.store.onboard("Race")
        auth = {"Authorization": "Bearer " + pin}
        root = "/v1/mini/t/race"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            chat = asyncio.create_task(
                client.post(root + "/chat", headers=auth, json={"message": "Hello"})
            )
            await asyncio.wait_for(entered.wait(), 2)
            erase = asyncio.create_task(
                client.post(
                    root + "/erase", headers=auth, json={"confirmation": "DELETE MY MINI DATA"}
                )
            )
            await asyncio.sleep(0.05)
            assert not erase.done()
            release.set()
            assert (await chat).status_code == 200
            assert (await erase).status_code == 200
            assert not app.state.store._tenant_path(tenant.slug).exists()
            assert (await client.get(root + "/profile", headers=auth)).status_code == 401

    asyncio.run(scenario())
