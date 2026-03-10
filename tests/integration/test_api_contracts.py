def test_health_system_contract(client):
    response = client.get("/api/health/system")
    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    for key in ("cpu_percent", "memory_percent", "disk_percent", "uptime_seconds"):
        assert key in body


def test_health_plugins_contract(client):
    response = client.get("/api/health/plugins")
    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert isinstance(body["items"], dict)


def test_benchmark_summary_contract(client, device_config_dev, tmp_path):
    db_path = tmp_path / "contract_benchmarks.db"
    device_config_dev.update_value("benchmarks_db_path", str(db_path), write=True)

    client.post("/update_now", data={"plugin_id": "clock"})
    response = client.get("/api/benchmarks/summary?window=24h")
    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert isinstance(body["count"], int)
    summary = body["summary"]
    for metric_name in ("request_ms", "generate_ms", "preprocess_ms", "display_ms"):
        assert metric_name in summary
        assert set(summary[metric_name].keys()) == {"p50", "p95"}


def test_refresh_info_contract(client):
    response = client.get("/refresh-info")
    assert response.status_code == 200
    body = response.get_json()
    for key in ("refresh_time", "image_hash", "refresh_type", "plugin_id"):
        assert key in body
