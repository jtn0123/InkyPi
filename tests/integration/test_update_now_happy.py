from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient

# pyright: reportMissingImports=false
from PIL import Image


def test_update_now_happy_path(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch, flask_app: Flask
) -> Any:
    # Mock plugin image generation
    import plugins.ai_text.ai_text as ai_text_mod

    def fake_generate_image(self, settings: Any, device_config: Any) -> Any:
        return Image.new("RGB", device_config.get_resolution(), "white")

    monkeypatch.setattr(
        ai_text_mod.AIText, "generate_image", fake_generate_image, raising=True
    )

    # Mock display
    called = {"displayed": False}

    def fake_display_image(
        image: Any, image_settings: Any = None, history_meta: Any = None
    ) -> None:
        called["displayed"] = True
        called["history_meta"] = history_meta

    display_manager = flask_app.config["DISPLAY_MANAGER"]
    monkeypatch.setattr(
        display_manager, "display_image", fake_display_image, raising=True
    )

    # Ensure background task is not running to use direct path
    refresh_task = flask_app.config["REFRESH_TASK"]
    refresh_task.running = False

    resp = client.post(
        "/update_now",
        data={
            "plugin_id": "ai_text",
            "textPrompt": "hello",
            "textModel": "gpt-4o",
            "title": "T",
        },
    )
    assert resp.status_code == 200
    assert resp.json.get("success") is True
    assert called["displayed"] is True
    # Regression for JTN-341: direct update_now path must pass history_meta
    # containing plugin_id so /plugin_latest_image/<plugin_id> can find it.
    assert called["history_meta"] is not None
    assert called["history_meta"].get("plugin_id") == "ai_text"
