"""Exercise direct synchronous requests and real queued jobs against one policy."""

import time

import pytest
from flask import Flask
from flask.testing import FlaskClient
from PIL import Image

from refresh_task.job_queue import reset_job_queue
from utils.plugin_errors import ScreenshotBackendError, URLValidationError


@pytest.mark.parametrize(
    ("case", "status", "code"),
    [
        ("image", 200, None),
        ("none", 200, None),
        ("url", 422, "validation_error"),
        ("backend", 503, "backend_unavailable"),
        ("timeout", 504, "manual_update_timeout"),
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
    import blueprints.plugin as blueprint

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
            assert fallbacks == [case != "url", case != "url"]
    finally:
        reset_job_queue()
