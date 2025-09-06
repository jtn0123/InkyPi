def test_health_endpoints(client):
    # Liveness is always OK
    r = client.get("/healthz")
    assert r.status_code == 200
    # Readiness reflects running state or web-only
    r2 = client.get("/readyz")
    assert r2.status_code in (200, 503)

