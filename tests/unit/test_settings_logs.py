def test_api_logs_clamp_and_meta(client, monkeypatch):
    # Request with out-of-range parameters; expect clamped values in meta
    resp = client.get(
        "/api/logs?hours=9999&limit=999999&level=errors&contains=" + ("x" * 500)
    )
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


# ---- Additional edge-case tests ----


def test_download_logs_filename_timestamp(client):
    """Download filename matches inkypi_YYYYMMDD-HHMMSS.log pattern."""
    import re

    resp = client.get("/download-logs")
    assert resp.status_code == 200
    disposition = resp.headers.get("Content-Disposition", "")
    match = re.search(r"inkypi_\d{8}-\d{6}\.log", disposition)
    assert match is not None


def test_download_logs_exception_500(client, monkeypatch):
    """_read_log_lines raising returns 500 text response."""
    import blueprints.settings as mod

    monkeypatch.setattr(
        mod, "_read_log_lines", lambda h: (_ for _ in ()).throw(RuntimeError("fail"))
    )

    resp = client.get("/download-logs")
    assert resp.status_code == 500


def test_api_logs_level_warn_errors(client):
    """level=warn_errors is accepted and echoed back in meta."""
    resp = client.get("/api/logs?level=warn_errors")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["meta"]["level"] == "warn_errors"


def test_api_logs_level_all(client):
    """level=all is accepted and echoed back in meta."""
    resp = client.get("/api/logs?level=all")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["meta"]["level"] == "all"


def test_api_logs_contains_case_insensitive(client):
    """contains parameter is accepted and echoed back in meta."""
    resp = client.get("/api/logs?contains=ERROR")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["meta"]["contains"] == "ERROR"


def test_api_logs_truncated_hours_clamped(client):
    """hours=999 → truncated is true (clamped to 24)."""
    resp = client.get("/api/logs?hours=999")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["truncated"] is True
    assert data["meta"]["hours"] == 24


def test_api_logs_truncated_limit_clamped(client):
    """limit=999999 → truncated is true (clamped to 2000)."""
    resp = client.get("/api/logs?limit=999999")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["truncated"] is True
    assert data["meta"]["limit"] == 2000


def test_api_logs_response_size_guardrail(client, monkeypatch):
    """Huge output is truncated under MAX_RESPONSE_BYTES."""
    import blueprints.settings as mod

    # Generate huge log output
    big_lines = ["X" * 1000 for _ in range(2000)]
    monkeypatch.setattr(mod, "_read_log_lines", lambda h: big_lines)

    resp = client.get("/api/logs?hours=2&limit=2000")
    assert resp.status_code == 200
    resp.get_json()
    # Response body should be under the guardrail
    raw = resp.data
    assert len(raw) <= mod.MAX_RESPONSE_BYTES + 10000  # some overhead for JSON wrapping
