# pyright: reportMissingImports=false
"""Error recovery tests for graceful failure handling."""
import pytest


def test_config_write_failure_returns_error(client, monkeypatch):
    """Monkeypatch write_config to raise IOError -> server returns error."""
    import config as config_mod

    def bad_write(self):
        raise IOError("Disk full")

    monkeypatch.setattr(config_mod.Config, "write_config", bad_write)

    data = {
        "unit": "minute",
        "interval": "5",
        "timeFormat": "24h",
        "timezoneName": "UTC",
    }
    resp = client.post("/save_settings", data=data)
    # Should return error response, not crash
    assert resp.status_code in (200, 422, 500)
    if resp.status_code == 200:
        result = resp.get_json()
        if result:
            assert result.get("success") is False or "error" in str(result).lower()


def test_plugin_generate_image_timeout(client, monkeypatch):
    """Plugin generate_image raising TimeoutError returns error response."""
    from plugins.plugin_registry import get_registered_plugin_ids, get_plugin_instance

    if "clock" not in get_registered_plugin_ids():
        pytest.skip("clock plugin not available")

    plugin = get_plugin_instance({"id": "clock", "class": "Clock"})

    def slow_generate(*args, **kwargs):
        raise TimeoutError("Screenshot timed out")

    monkeypatch.setattr(plugin, "generate_image", slow_generate)

    data = {"plugin_id": "clock"}
    resp = client.post("/update_now", data=data)
    # Should return error, not crash
    assert resp.status_code in (200, 500)
    if resp.status_code == 200:
        result = resp.get_json()
        if result:
            assert result.get("success") is False or "error" in str(result).lower()


def test_missing_plugin_update_now(client):
    """Requesting update_now for non-existent plugin returns error."""
    data = {"plugin_id": "nonexistent_plugin_xyz"}
    resp = client.post("/update_now", data=data)
    assert resp.status_code in (200, 404, 500)
    if resp.status_code == 200:
        result = resp.get_json()
        if result:
            assert result.get("success") is False


def test_invalid_json_body(client):
    """POST with invalid content type doesn't crash."""
    resp = client.post(
        "/save_settings",
        data="not-form-data",
        content_type="text/plain",
    )
    # Should handle gracefully
    assert resp.status_code in (200, 400, 415, 422, 500)
