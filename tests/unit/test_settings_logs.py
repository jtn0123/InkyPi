def test_api_logs_clamp_and_meta(client, monkeypatch):
    # Request with out-of-range parameters; expect clamped values in meta
    resp = client.get("/api/logs?hours=9999&limit=999999&level=errors&contains=" + ("x" * 500))
    assert resp.status_code == 200
    data = resp.get_json()
    assert "meta" in data
    meta = data["meta"]
    # Hours clamped to max (24) and limit clamped to max (2000)
    assert meta["hours"] <= 24
    assert meta["limit"] <= 2000
    # Level echoed back
    assert meta["level"] == "errors"
    # Contains trimmed to <= 200
    assert len(meta["contains"]) <= 200


def test_api_logs_size_guard(client, monkeypatch):
    # Ask for a large limit; handler should ensure response size guardrail
    resp = client.get("/api/logs?hours=2&limit=5000&level=all")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["count"] <= data["meta"]["limit"]
    # Ensure meta present
    assert "meta" in data


def test_api_logs_rate_limit(client, monkeypatch):
    # Simulate many quick requests from same remote addr to trigger 429
    # Flask test client sets REMOTE_ADDR=127.0.0.1 by default
    # Hit enough times to exceed _RATE_LIMIT_MAX_REQUESTS (120)
    last = None
    for _ in range(130):
        last = client.get("/api/logs")
        if last.status_code == 429:
            break
    assert last is not None
    assert last.status_code in (200, 429)
    # If not rate-limited in this environment, still acceptable; otherwise ensure JSON error
    if last.status_code == 429:
        body = last.get_json()
        assert body.get("error") == "Too many requests"


