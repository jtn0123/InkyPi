"""Exercise direct synchronous requests and real queued jobs against one policy."""

import time
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient
from PIL import Image

from refresh_task.job_queue import reset_job_queue
from utils.plugin_errors import (
    PROVIDER_REJECTED_MSG,
    ProviderReportedPluginError,
    ScreenshotBackendError,
    URLValidationError,
)


@pytest.mark.parametrize(
    ("case", "status", "code"),
    [
        ("image", 200, None),
        ("none", 200, None),
        ("url", 422, "validation_error"),
        ("backend", 503, "backend_unavailable"),
        ("timeout", 504, "manual_update_timeout"),
        ("provider", 400, "provider_rejected"),
        ("runtime", 400, "plugin_error"),
        ("unexpected", 500, "internal_error"),
        ("display", 500, "internal_error"),
    ],
)
def test_direct_request_and_queued_job_match(
    client: FlaskClient,
    flask_app: Flask,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    status: int,
    code: str | None,
) -> None:
    import blueprints.plugin._update_now as blueprint

    flask_app.config["REFRESH_TASK"].running = False
    displayed: list[object] = []
    fallbacks: list[bool] = []

    class Plugin:
        def generate_image(
            self, settings: object, config: object
        ) -> Image.Image | None:
            if case == "none":
                return None
            errors = {
                "url": URLValidationError("sensitive URL"),
                "backend": ScreenshotBackendError("sensitive renderer path"),
                "timeout": TimeoutError("sensitive process details"),
                "provider": ProviderReportedPluginError("sensitive upstream body"),
                "runtime": RuntimeError("sensitive provider key"),
                "unexpected": ValueError("sensitive traceback"),
            }
            if case in errors:
                raise errors[case]
            return Image.new("RGB", (8, 8), "white")

    def display(image: object, **kwargs: object) -> None:
        if case == "display":
            raise RuntimeError("sensitive driver details")
        displayed.append(image)

    def fallback(*args: object, record_history: bool = True) -> None:
        fallbacks.append(record_history)

    monkeypatch.setattr(blueprint, "get_plugin_instance", lambda config: Plugin())
    monkeypatch.setattr(blueprint, "_push_update_now_fallback", fallback)
    monkeypatch.setattr(flask_app.config["DISPLAY_MANAGER"], "display_image", display)
    reset_job_queue()
    try:
        synchronous = client.post("/update_now", data={"plugin_id": "clock"})
        body = synchronous.get_json()
        assert body is not None
        assert synchronous.status_code == status
        accepted = client.post(
            "/update_now", data={"plugin_id": "clock"}, headers={"X-Async": "true"}
        )
        job = accepted.get_json()
        assert job is not None and accepted.status_code == 202
        deadline = time.monotonic() + 3
        while True:
            response = client.get(f'/api/job/{job["job_id"]}')
            queued = response.get_json()
            assert queued is not None
            if queued["status"] in {"done", "error"}:
                break
            assert time.monotonic() < deadline, queued
            time.sleep(0.005)
        if status == 200:
            assert queued["status"] == "done"
            assert queued["result"]["message"] == body["message"]
            assert queued["result"]["success"] is True
            if case == "none":
                assert (
                    body["metrics"] == queued["result"]["metrics"] == {"no_image": True}
                )
                assert not displayed
            else:
                assert len(displayed) == 2
                assert set(body["metrics"]) == set(queued["result"]["metrics"])
            assert not fallbacks
        else:
            assert queued["status"] == "error"
            assert queued["http_status"] == status
            assert queued["code"] == body["code"] == code
            assert queued["error"] == body["error"]
            assert "sensitive" not in str(queued) + str(body)
            if case == "provider":
                # The provider's safe summary, not "An internal error occurred".
                assert body["error"] == PROVIDER_REJECTED_MSG
            assert fallbacks == [case != "url", case != "url"]
    finally:
        reset_job_queue()


def _seed_clock_playlist(device_config: Any) -> None:
    pm = device_config.get_playlist_manager()
    if not pm.get_playlist("Default"):
        pm.add_playlist("Default", "00:00", "24:00")
    pm.get_playlist("Default").add_plugin(
        {
            "plugin_id": "clock",
            "name": "Clock Parity",
            "plugin_settings": {},
            "refresh": {"interval": 300},
        }
    )
    device_config.write_config()


@pytest.mark.parametrize(
    "case",
    ["image", "none", "url", "backend", "timeout", "provider", "runtime", "unexpected"]
    + ["display"],
)
def test_display_next_and_update_now_answer_alike(
    client: FlaskClient,
    flask_app: Flask,
    device_config_dev: Any,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    """With the refresh loop stopped, "Display next" renders in the request
    like "Update now". It kept its own copy of the outcome rules, which had
    drifted: no image was 409 there and 200 here, and it caught only
    RuntimeError, so a rejected URL, a timeout or chromium being down came
    back as 400 or 500 instead of their own status and code."""
    import blueprints.main as main
    import blueprints.plugin._update_now as update_now
    from plugins import plugin_registry

    flask_app.config["REFRESH_TASK"].running = False
    _seed_clock_playlist(device_config_dev)
    errors = {
        "url": URLValidationError("sensitive URL"),
        "backend": ScreenshotBackendError("sensitive renderer path"),
        "timeout": TimeoutError("sensitive process details"),
        "provider": ProviderReportedPluginError("sensitive upstream body"),
        "runtime": RuntimeError("sensitive provider key"),
        "unexpected": ValueError("sensitive traceback"),
    }

    class Plugin:
        def generate_image(
            self, settings: object, config: object
        ) -> Image.Image | None:
            if case == "none":
                return None
            if case in errors:
                raise errors[case]
            return Image.new("RGB", (8, 8), "white")

    def display(image: object, **kwargs: object) -> dict[str, int]:
        if case == "display":
            raise RuntimeError("sensitive driver details")
        return {"display_ms": 7, "preprocess_ms": 3}

    monkeypatch.setattr(update_now, "get_plugin_instance", lambda config: Plugin())
    monkeypatch.setattr(plugin_registry, "get_plugin_instance", lambda c: Plugin())
    monkeypatch.setattr(update_now, "_push_update_now_fallback", lambda *a, **k: None)
    monkeypatch.setattr(flask_app.config["DISPLAY_MANAGER"], "display_image", display)
    main._reset_display_next_cooldown()

    reference = client.post("/update_now", data={"plugin_id": "clock"})
    response = client.post("/display-next")
    main._reset_display_next_cooldown()

    body, expected = response.get_json(), reference.get_json()
    assert response.status_code == reference.status_code, (body, expected)
    assert body["success"] is expected["success"]
    assert body.get("code") == expected.get("code")
    assert "sensitive" not in response.get_data(as_text=True)
    if case == "none":
        assert response.status_code == 200
        assert body["message"] == expected["message"]
        assert body["metrics"] == {"no_image": True}
    elif case == "image":
        assert body["message"] == "Display updated"
        assert set(body["metrics"]) == set(expected["metrics"])
    elif case == "runtime":
        # Same status and code; the route keeps its own wording.
        assert body["error"] == "Plugin image generation failed"
    else:
        assert body["error"] == expected["error"]


def test_display_next_leaves_the_panel_and_refresh_info_alone_without_an_image(
    client: FlaskClient,
    flask_app: Flask,
    device_config_dev: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A control-only plugin returning no image is a completed refresh with
    nothing to show (as in the refresh loop), not a 409 conflict: the
    dashboard showed "Failed to display next" for a plugin that worked."""
    import blueprints.main as main
    from plugins import plugin_registry

    flask_app.config["REFRESH_TASK"].running = False
    _seed_clock_playlist(device_config_dev)

    class ControlOnly:
        def generate_image(self, settings: object, config: object) -> None:
            return None

    displayed: list[object] = []
    monkeypatch.setattr(plugin_registry, "get_plugin_instance", lambda c: ControlOnly())
    monkeypatch.setattr(
        flask_app.config["DISPLAY_MANAGER"],
        "display_image",
        lambda image, **kwargs: displayed.append(image),
    )
    before = device_config_dev.get_refresh_info().to_dict()
    main._reset_display_next_cooldown()

    response = client.post("/display-next")
    main._reset_display_next_cooldown()

    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert body["metrics"] == {"no_image": True}
    assert not displayed
    after = device_config_dev.get_refresh_info().to_dict()
    assert after == before


def test_display_next_records_the_display_timings(
    client: FlaskClient,
    flask_app: Flask,
    device_config_dev: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The direct path used to report and store None for the display and
    preprocess times the display manager had just measured."""
    import blueprints.main as main
    from plugins import plugin_registry

    flask_app.config["REFRESH_TASK"].running = False
    _seed_clock_playlist(device_config_dev)

    class Plugin:
        def generate_image(self, settings: object, config: object) -> Image.Image:
            return Image.new("RGB", (8, 8), "white")

    monkeypatch.setattr(plugin_registry, "get_plugin_instance", lambda c: Plugin())
    monkeypatch.setattr(
        flask_app.config["DISPLAY_MANAGER"],
        "display_image",
        lambda image, **kwargs: {"display_ms": 7, "preprocess_ms": 3},
    )
    main._reset_display_next_cooldown()

    response = client.post("/display-next")
    main._reset_display_next_cooldown()

    assert response.status_code == 200
    metrics = response.get_json()["metrics"]
    assert (metrics["display_ms"], metrics["preprocess_ms"]) == (7, 3)
    assert metrics["request_ms"] is not None
    info = device_config_dev.get_refresh_info()
    assert (info.display_ms, info.preprocess_ms) == (7, 3)
    assert info.plugin_instance == "Clock Parity"
