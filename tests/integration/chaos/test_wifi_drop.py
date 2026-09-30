from __future__ import annotations

from threading import Event
from time import monotonic, sleep
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient
from PIL import Image


def test_wifi_drop_mid_refresh_then_retry_succeeds(
    client: FlaskClient, flask_app: Flask, monkeypatch: pytest.MonkeyPatch
) -> Any:
    refresh_task = flask_app.config["REFRESH_TASK"]
    device_config = flask_app.config["DEVICE_CONFIG"]
    monkeypatch.setenv("INKYPI_PLUGIN_RETRY_MAX", "0")
    monkeypatch.setenv("INKYPI_MANUAL_UPDATE_DONE_GRACE_S", "0")

    # Hold the hardware phase after image_saved to exercise the API's early
    # response deterministically, rather than depending on host scheduling.
    release_display = Event()
    display_image = refresh_task.display_manager.display_image

    def delayed_display(*args: Any, **kwargs: Any) -> Any:
        on_saved = kwargs.get("on_image_saved")
        if on_saved is not None:

            def saved(metrics: Any) -> None:
                on_saved(metrics)
                assert release_display.wait(5), "Test did not release the display phase"

            kwargs["on_image_saved"] = saved
        return display_image(*args, **kwargs)

    monkeypatch.setattr(refresh_task.display_manager, "display_image", delayed_display)

    class FlakyWifiPlugin:
        def __init__(self) -> None:
            self.calls = 0

        def generate_image(self, _settings: Any, cfg: Any) -> Any:
            self.calls += 1
            if self.calls == 1:
                raise ConnectionError("wifi dropped for 60s")
            return Image.new("RGB", cfg.get_resolution(), "white")

        def get_latest_metadata(self) -> Any:
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

        release_display.set()
        deadline = monotonic() + 5
        while True:
            diag_after_retry = client.get("/api/diagnostics").get_json()
            if diag_after_retry["refresh_task"]["last_error"] is None:
                break
            assert (
                monotonic() < deadline
            ), "Successful refresh did not clear the Wi-Fi error"
            sleep(0.01)
    finally:
        release_display.set()
        refresh_task.stop()
