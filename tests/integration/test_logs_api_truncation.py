def test_logs_api_truncation_and_level_filter(client, monkeypatch):
    from blueprints import settings as settings_mod

    # Monkeypatch readers to return controlled lines
    def fake_read_log_lines(hours):
        # Include errors and warnings and info lines
        return [
            "INFO normal line",
            "WARNING something odd",
            "ERROR failed to do thing",
        ] * 1000  # many lines to trigger truncation/byte cap

    monkeypatch.setattr(settings_mod, "_read_log_lines", fake_read_log_lines, raising=True)

    # errors level should only return error lines and be truncated
    r = client.get("/api/logs?hours=2&limit=100&level=errors")
    assert r.status_code == 200
    data = r.get_json()
    assert data["truncated"] is True
    assert all("ERROR" in ln for ln in data["lines"])  # only errors

    # warnings+errors
    r2 = client.get("/api/logs?hours=2&limit=100&level=warn")
    data2 = r2.get_json()
    assert any("WARNING" in ln for ln in data2["lines"]) and any("ERROR" in ln for ln in data2["lines"])  # mixed

