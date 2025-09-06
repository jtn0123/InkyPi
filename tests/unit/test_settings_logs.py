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


