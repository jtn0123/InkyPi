from __future__ import annotations

from PIL import Image


def test_wifi_drop_mid_refresh_then_retry_succeeds(client, flask_app, monkeypatch):
    refresh_task = flask_app.config["REFRESH_TASK"]
    device_config = flask_app.config["DEVICE_CONFIG"]
    monkeypatch.setenv("INKYPI_PLUGIN_RETRY_MAX", "0")

    class FlakyWifiPlugin:
        def __init__(self):
            self.calls = 0

        def generate_image(self, _settings, cfg):
            self.calls += 1
            if self.calls == 1:
                raise ConnectionError("wifi dropped for 60s")
            return Image.new("RGB", cfg.get_resolution(), "white")

        def get_latest_metadata(self):
            return None

    plugin = FlakyWifiPlugin()

    monkeypatch.setattr(
        device_config,
        "get_plugin",
        lambda plugin_id: {"id": plugin_id, "class": "WifiDrop", "image_settings": []},
        raising=True,
    )
    monkeypatch.setattr(
        "refresh_task.task.get_plugin_instance",
        lambda _cfg: plugin,
        raising=True,
    )

    refresh_task.start()
    try:
        first = client.post("/update_now", data={"plugin_id": "wifi_fault"})
        assert first.status_code == 500

        diag_after_fail = client.get("/api/diagnostics").get_json()
        last_error = diag_after_fail["refresh_task"]["last_error"] or ""
        assert "wifi dropped" in last_error.lower()

        second = client.post("/update_now", data={"plugin_id": "wifi_fault"})
        assert second.status_code == 200

        diag_after_retry = client.get("/api/diagnostics").get_json()
        assert diag_after_retry["refresh_task"]["last_error"] is None
    finally:
        refresh_task.stop()
