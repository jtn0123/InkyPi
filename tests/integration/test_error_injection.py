# pyright: reportMissingImports=false
import json
import os

import pytest
from PIL import Image


def _valid_ai_text_settings():
    return {"title": "T", "textModel": "gpt-4o", "textPrompt": "Hi"}


def test_manual_update_propagates_plugin_exception(device_config_dev, monkeypatch):
    # Ensure plugin registry is loaded
    from plugins.plugin_registry import load_plugins

    load_plugins(device_config_dev.get_plugins())

    # Force AI Text plugin to raise on generate_image
    import plugins.ai_text.ai_text as ai_text_mod

    def boom(self, settings, device_config):
        raise RuntimeError("boom")

    monkeypatch.setattr(ai_text_mod.AIText, "generate_image", boom, raising=True)

    # Start refresh task and attempt manual update
    from display.display_manager import DisplayManager
    from refresh_task import ManualRefresh, RefreshTask

    display_manager = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, display_manager)

    try:
        task.start()
        os.environ["OPEN_AI_SECRET"] = "test"
        with pytest.raises(RuntimeError):
            task.manual_update(ManualRefresh("ai_text", _valid_ai_text_settings()))
    finally:
        task.stop()


def test_update_now_returns_500_when_display_raises(client, monkeypatch):
    # Return a simple image from plugin
    import plugins.ai_text.ai_text as ai_text_mod

    def ok_img(self, settings, device_config):
        return Image.new("RGB", device_config.get_resolution(), "white")

    monkeypatch.setattr(ai_text_mod.AIText, "generate_image", ok_img, raising=True)

    # Make display manager raise
    app = client.application
    display_manager = app.config["DISPLAY_MANAGER"]

    def raise_display(img, image_settings=None):
        raise RuntimeError("display failure")

    monkeypatch.setattr(display_manager, "display_image", raise_display, raising=True)

    os.environ["OPEN_AI_SECRET"] = "test"
    resp = client.post(
        "/update_now",
        data={
            "plugin_id": "ai_text",
            **_valid_ai_text_settings(),
        },
    )
    assert resp.status_code == 500


def test_display_plugin_instance_returns_500_on_plugin_error(
    client, device_config_dev, monkeypatch
):
    # Prepare a playlist with an ai_text instance
    pm = device_config_dev.get_playlist_manager()
    pm.add_playlist("P1", "00:00", "24:00")
    pm.add_plugin_to_playlist(
        "P1",
        {
            "plugin_id": "ai_text",
            "name": "inst",
            "plugin_settings": _valid_ai_text_settings(),
            "refresh": {"interval": 1},
        },
    )

    # Ensure plugin registry is loaded
    from plugins.plugin_registry import load_plugins

    load_plugins(device_config_dev.get_plugins())

    # Force plugin to raise during image generation
    import plugins.ai_text.ai_text as ai_text_mod

    def boom(self, settings, device_config):
        raise RuntimeError("boom")

    monkeypatch.setattr(ai_text_mod.AIText, "generate_image", boom, raising=True)

    # Start background task so manual_update executes
    app = client.application
    task = app.config["REFRESH_TASK"]
    try:
        task.start()
        os.environ["OPEN_AI_SECRET"] = "test"
        resp = client.post(
            "/display_plugin_instance",
            json={
                "playlist_name": "P1",
                "plugin_id": "ai_text",
                "plugin_instance": "inst",
            },
        )
        assert resp.status_code == 500
    finally:
        task.stop()


def test_plugin_settings_page_returns_500_on_template_error(client, monkeypatch):
    # Make generate_settings_template raise
    import plugins.ai_text.ai_text as ai_text_mod

    def raise_settings(self):
        raise RuntimeError("template error")

    monkeypatch.setattr(
        ai_text_mod.AIText, "generate_settings_template", raise_settings, raising=True
    )

    resp = client.get("/plugin/ai_text")
    assert resp.status_code == 500


def test_add_plugin_returns_500_when_write_config_fails(
    client, device_config_dev, monkeypatch
):
    # Existing playlist
    pm = device_config_dev.get_playlist_manager()
    pm.add_playlist("P1", "00:00", "24:00")

    # Make write_config raise
    def raise_write():
        raise RuntimeError("write failed")

    monkeypatch.setattr(device_config_dev, "write_config", raise_write, raising=True)

    payload = {
        "plugin_id": "ai_text",
        "refresh_settings": json.dumps(
            {
                "playlist": "P1",
                "instance_name": "inst",
                "refreshType": "interval",
                "unit": "minute",
                "interval": 1,
            }
        ),
        **_valid_ai_text_settings(),
    }
    os.environ["OPEN_AI_SECRET"] = "test"
    resp = client.post("/add_plugin", data=payload)
    assert resp.status_code == 500
