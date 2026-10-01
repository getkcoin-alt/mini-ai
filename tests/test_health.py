def test_liveness_and_readiness(app_client):
    client, _, _ = app_client
    live = client.get("/health/live")
    ready = client.get("/health/ready")

    assert live.status_code == 200
    assert live.json()["status"] == "ok"
    assert live.headers["x-content-type-options"] == "nosniff"
    assert live.headers["cache-control"] == "no-store"
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert ready.json()["checks"]["vault"] == "ok"


def test_admin_endpoints_fail_closed(app_client):
    client, _, _ = app_client
    assert client.get("/v1/mini/admin/tenants").status_code == 401
    assert client.get(
        "/v1/mini/admin/tenants", headers={"Authorization": "Bearer wrong"}
    ).status_code == 401
