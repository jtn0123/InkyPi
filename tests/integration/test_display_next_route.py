from datetime import datetime, timezone

import pytest
from PIL import Image


def _fixed_now(_device_config):
    return datetime(2025, 1, 1, 8, 0, 0, tzinfo=timezone.utc)


def _add_playlist_with_plugin(device_config):
    pm = device_config.get_playlist_manager()
    if not pm.get_playlist("Default"):
        pm.add_playlist("Default", "00:00", "24:00")
    pl = pm.get_playlist("Default")
    pl.add_plugin(
        {
            "plugin_id": "clock",
            "name": "Clock A",
            "plugin_settings": {},
            "refresh": {"interval": 300},
        }
    )
    device_config.write_config()


def _add_empty_playlist(device_config):
    pm = device_config.get_playlist_manager()
    if not pm.get_playlist("Default"):
        pm.add_playlist("Default", "00:00", "24:00")
    device_config.write_config()


@pytest.mark.integration
def test_display_next_returns_metrics(client, device_config_dev, monkeypatch, flask_app):
    flask_app.config["REFRESH_TASK"].running = False

    _add_playlist_with_plugin(device_config_dev)
    monkeypatch.setattr("utils.time_utils.now_device_tz", _fixed_now, raising=True)

    from plugins import plugin_registry

    class _StubPlugin:
        def generate_image(self, settings, device_config):
            return Image.new("RGB", (800, 480), "white")

    monkeypatch.setattr(
        plugin_registry, "get_plugin_instance", lambda cfg: _StubPlugin(), raising=True
    )

    displayed = {"called": False}

    def _display_image(image, image_settings=None, history_meta=None):
        displayed["called"] = True

    flask_app.config["DISPLAY_MANAGER"].display_image = _display_image

    resp = client.post("/display-next")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body.get("success") is True
    assert displayed["called"] is True
    metrics = body.get("metrics")
    assert isinstance(metrics, dict)
    for key in ("request_ms", "generate_ms", "preprocess_ms", "display_ms"):
        assert key in metrics
    assert metrics["generate_ms"] is not None


@pytest.mark.integration
def test_display_next_no_playlist_returns_error(client, device_config_dev, monkeypatch, flask_app):
    flask_app.config["REFRESH_TASK"].running = False
    monkeypatch.setattr("utils.time_utils.now_device_tz", _fixed_now, raising=True)
    pm = device_config_dev.get_playlist_manager()
    monkeypatch.setattr(pm, "determine_active_playlist", lambda dt: None, raising=True)

    resp = client.post("/display-next")
    assert resp.status_code == 400
    body = resp.get_json()
    assert body.get("success") is False
    assert body.get("error") == "No active playlist"


@pytest.mark.integration
def test_display_next_no_plugin_returns_error(client, device_config_dev, monkeypatch, flask_app):
    flask_app.config["REFRESH_TASK"].running = False
    _add_empty_playlist(device_config_dev)
    monkeypatch.setattr("utils.time_utils.now_device_tz", _fixed_now, raising=True)

    resp = client.post("/display-next")
    assert resp.status_code == 400
    body = resp.get_json()
    assert body.get("success") is False
    assert body.get("error") == "No eligible plugin to display"
