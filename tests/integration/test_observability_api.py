import time


def test_benchmarks_summary_refreshes_and_plugins(client, device_config_dev, tmp_path):
    db_path = tmp_path / "benchmarks.db"
    device_config_dev.update_value("benchmarks_db_path", str(db_path), write=True)

    # Trigger at least one refresh event
    r = client.post("/update_now", data={"plugin_id": "clock"})
    assert r.status_code == 200

    s = client.get("/api/benchmarks/summary?window=24h")
    assert s.status_code == 200
    sj = s.get_json()
    assert sj.get("success") is True
    assert "summary" in sj

    rr = client.get("/api/benchmarks/refreshes?limit=5")
    assert rr.status_code == 200
    rj = rr.get_json()
    assert rj.get("success") is True
    assert isinstance(rj.get("items"), list)

    p = client.get("/api/benchmarks/plugins?window=24h")
    assert p.status_code == 200
    pj = p.get_json()
    assert pj.get("success") is True
    assert isinstance(pj.get("items"), list)


def test_benchmarks_stages_validation(client):
    r = client.get("/api/benchmarks/stages")
    assert r.status_code == 422
    j = r.get_json()
    assert j.get("success") is False
    assert j.get("code") == "validation_error"


def test_health_endpoints(client):
    hp = client.get("/api/health/plugins")
    hs = client.get("/api/health/system")
    assert hp.status_code == 200
    assert hs.status_code == 200
    assert hp.get_json().get("success") is True
    assert hs.get_json().get("success") is True


def test_isolation_endpoints(client):
    g = client.get("/settings/isolation")
    assert g.status_code == 200
    assert g.get_json().get("success") is True

    p = client.post("/settings/isolation", json={"plugin_id": "clock"})
    assert p.status_code == 200
    assert "clock" in p.get_json().get("isolated_plugins", [])

    d = client.delete("/settings/isolation", json={"plugin_id": "clock"})
    assert d.status_code == 200
    assert "clock" not in d.get_json().get("isolated_plugins", [])


def test_safe_reset_endpoint(client):
    r = client.post("/settings/safe_reset")
    assert r.status_code == 200
    j = r.get_json()
    assert j.get("success") is True


def test_progress_stream_sse(client):
    # Hit endpoint to ensure it is streamable and emits event syntax
    r = client.get("/api/progress/stream", buffered=False)
    assert r.status_code == 200
    first = next(r.response)
    body = first.decode("utf-8", errors="ignore")
    # stream may start with keep-alive if no events yet
    assert "event:" in body or ": keep-alive" in body
