"""Known render failures get the same status and code on every display route.

Before this, blackout during "Display next" returned 400 "Plugin update failed"
on one route and a generic 500 on two others, and a timeout was 504 on
``/update_now`` only. ``route_error_for`` is now the one mapping, and every
route that asks the refresh loop to render goes through it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient
from werkzeug.test import TestResponse

from utils.backend_errors import (
    ConflictRouteError,
    InternalOperationError,
    mapped_render_errors,
    route_error_boundary,
    route_error_for,
)
from utils.blackout import BLOCKED_MESSAGE, BlackoutActiveError
from utils.domain_errors import (
    DomainError,
    PluginNotFound,
    PluginRenderFailed,
    RefreshLoopBusy,
    RefreshTaskUnavailable,
)
from utils.plugin_errors import (
    ProviderReportedPluginError,
    ScreenshotBackendError,
    URLValidationError,
)

_INSTANCE = "Clock Mapping"
# Exception text that must never reach a response body.
_SECRET = "/var/lib/inkypi/secret-path: upstream said no"


def _render_failed(cause: BaseException | None = None) -> PluginRenderFailed:
    """A failed render as the refresh cycle raises it."""
    failed = PluginRenderFailed(_SECRET)
    failed.__cause__ = cause
    return failed


# (id, make the failure, expected status, expected code)
_FAILURES: list[tuple[str, Callable[[], BaseException], int, str]] = [
    ("blackout", BlackoutActiveError, 409, "blackout_active"),
    ("loop-stopped", RefreshTaskUnavailable, 503, "refresh_task_unavailable"),
    ("loop-busy", RefreshLoopBusy, 503, "refresh_loop_busy"),
    ("timeout", lambda: TimeoutError(_SECRET), 504, "manual_update_timeout"),
    (
        "bad-url",
        lambda: URLValidationError(f"Invalid URL: {_SECRET}"),
        422,
        "validation_error",
    ),
    (
        "provider",
        lambda: ProviderReportedPluginError(_SECRET),
        400,
        "provider_rejected",
    ),
    (
        "chromium",
        lambda: ScreenshotBackendError(_SECRET),
        503,
        "backend_unavailable",
    ),
    ("plugin-missing", PluginNotFound, 404, "plugin_not_found"),
    (
        "render-failed",
        lambda: _render_failed(RuntimeError(_SECRET)),
        400,
        "plugin_error",
    ),
    # A failed render whose cause has its own answer is reported as that.
    (
        "render-bad-url",
        lambda: _render_failed(URLValidationError(f"Invalid URL: {_SECRET}")),
        422,
        "validation_error",
    ),
]

_ROUTES: dict[str, Callable[[FlaskClient], TestResponse]] = {
    "update_now": lambda c: c.post("/update_now", data={"plugin_id": "clock"}),
    "display-next": lambda c: c.post("/display-next"),
    "display_next_in_playlist": lambda c: c.post(
        "/display_next_in_playlist", json={"playlist_name": "Default"}
    ),
    "display_plugin_instance": lambda c: c.post(
        "/display_plugin_instance",
        json={
            "playlist_name": "Default",
            "plugin_id": "clock",
            "plugin_instance": _INSTANCE,
        },
    ),
}


def _seed_default_playlist(device_config_dev: Any) -> None:
    pm = device_config_dev.get_playlist_manager()
    if not pm.get_playlist("Default"):
        pm.add_playlist("Default", "00:00", "24:00")
    pm.get_playlist("Default").add_plugin(
        {
            "plugin_id": "clock",
            "name": _INSTANCE,
            "plugin_settings": {},
            "refresh": {"interval": 300},
        }
    )


@pytest.mark.parametrize("route", list(_ROUTES), ids=list(_ROUTES))
@pytest.mark.parametrize(
    ("make_error", "status", "code"),
    [f[1:] for f in _FAILURES],
    ids=[f[0] for f in _FAILURES],
)
def test_render_failure_maps_the_same_on_every_route(
    client: FlaskClient,
    device_config_dev: Any,
    flask_app: Flask,
    monkeypatch: pytest.MonkeyPatch,
    route: str,
    make_error: Callable[[], BaseException],
    status: int,
    code: str,
) -> None:
    import blueprints.main as main_mod

    _seed_default_playlist(device_config_dev)
    main_mod._display_next_limiter.reset()
    rt = flask_app.config["REFRESH_TASK"]
    monkeypatch.setattr(rt, "running", True)

    def _fail(_action: Any) -> None:
        raise make_error()

    monkeypatch.setattr(rt, "manual_update", _fail)

    resp = _ROUTES[route](client)

    assert resp.status_code == status
    body = resp.get_json()
    assert body["code"] == code
    assert _SECRET not in resp.get_data(as_text=True)
    if code == "blackout_active":
        assert body["error"] == BLOCKED_MESSAGE


@pytest.mark.parametrize(
    ("make_error", "status", "code"),
    [f[1:] for f in _FAILURES]
    + [(lambda: RuntimeError(_SECRET), 500, "internal_error")],
    ids=[f[0] for f in _FAILURES] + ["unmapped"],
)
def test_queued_update_now_reports_what_the_synchronous_route_does(
    client: FlaskClient,
    flask_app: Flask,
    monkeypatch: pytest.MonkeyPatch,
    make_error: Callable[[], BaseException],
    status: int,
    code: str,
) -> None:
    # The plugin page sends "Update now" as a queued job and shows the job's
    # error. With the refresh loop running (the normal case on the Pi) that
    # error used to be the raw exception text.
    from services.job_queue import get_job_queue, reset_job_queue

    rt = flask_app.config["REFRESH_TASK"]
    monkeypatch.setattr(rt, "running", True)

    def _fail(_action: Any) -> None:
        raise make_error()

    monkeypatch.setattr(rt, "manual_update", _fail)
    reset_job_queue()
    try:
        synchronous = client.post("/update_now", data={"plugin_id": "clock"})
        accepted = client.post(
            "/update_now", data={"plugin_id": "clock"}, headers={"X-Async": "true"}
        )
        assert accepted.status_code == 202
        job_id = accepted.get_json()["job_id"]
        get_job_queue().shutdown(wait=True)
        job = client.get(f"/api/job/{job_id}").get_json()
    finally:
        reset_job_queue()

    body = synchronous.get_json()
    assert job["status"] == "error"
    assert synchronous.status_code == job["http_status"] == status
    assert body["code"] == job["code"] == code
    assert job["error"] == body["error"]
    assert job.get("details") == body.get("details")
    assert _SECRET not in str(job)


def test_blackout_message_tells_the_user_why() -> None:
    mapped = route_error_for(BlackoutActiveError())
    assert isinstance(mapped, ConflictRouteError)
    assert mapped.message == BLOCKED_MESSAGE


@pytest.mark.parametrize(
    "err",
    [RuntimeError("boom"), ValueError("boom"), DomainError("unmapped")],
    ids=["runtime", "value", "bare-domain"],
)
def test_unknown_failures_are_not_mapped(err: BaseException) -> None:
    assert route_error_for(err) is None


def test_mapped_render_errors_lets_unknown_failures_through() -> None:
    with pytest.raises(KeyError):
        with mapped_render_errors("render"):
            raise KeyError("missing")


def test_route_boundary_maps_domain_errors_and_hides_the_rest() -> None:
    with pytest.raises(ConflictRouteError) as blackout:
        with route_error_boundary("display"):
            raise BlackoutActiveError
    assert blackout.value.code == "blackout_active"

    # A plugin failure that is not a DomainError stays an internal error here;
    # routes that render opt in with mapped_render_errors.
    with pytest.raises(InternalOperationError):
        with route_error_boundary("display"):
            raise ScreenshotBackendError(_SECRET)


def test_app_handler_maps_domain_errors_that_escape_a_route(
    flask_app: Flask,
) -> None:
    def _blackout() -> str:
        raise BlackoutActiveError

    def _unmapped() -> str:
        raise DomainError("no mapping for this one")

    flask_app.add_url_rule("/_test/blackout", "_test_blackout", _blackout)
    flask_app.add_url_rule("/_test/unmapped", "_test_unmapped", _unmapped)
    client = flask_app.test_client()

    resp = client.get("/_test/blackout", headers={"Accept": "application/json"})
    assert resp.status_code == 409
    assert resp.get_json()["code"] == "blackout_active"

    resp = client.get("/_test/unmapped", headers={"Accept": "application/json"})
    assert resp.status_code == 500
    assert "no mapping for this one" not in resp.get_data(as_text=True)


# Run in a fresh interpreter: imports every refresh_task module (and
# utils.blackout, which the loop uses), then reports which web-layer modules
# that loaded.
_REFRESH_LOOP_IMPORT_PROBE = """
import importlib, json, pkgutil, sys

import refresh_task
import utils.blackout

imported = [
    importlib.import_module(info.name).__name__
    for info in pkgutil.walk_packages(refresh_task.__path__, "refresh_task.")
]
web_layer = ("services", "blueprints", "flask", "utils.backend_errors")
loaded = sorted(
    name
    for name in sys.modules
    if any(name == root or name.startswith(root + ".") for root in web_layer)
)
print(json.dumps({"imported": imported, "loaded": loaded}))
"""


def test_refresh_loop_does_not_import_the_web_layer() -> None:
    """No refresh_task module loads the routes, services, Flask or route errors.

    Every module in the package is imported, not only the ones the loop loads
    at run time, so a web-only module placed in refresh_task/ still fails this.
    """
    src = Path(__file__).resolve().parents[2] / "src"
    env = {**os.environ, "PYTHONPATH": str(src)}
    out = subprocess.run(
        [sys.executable, "-c", _REFRESH_LOOP_IMPORT_PROBE],
        capture_output=True,
        text=True,
        env=env,
        check=True,
        timeout=60,
    )
    result = json.loads(out.stdout)
    assert "refresh_task.task" in result["imported"]
    assert "refresh_task.command_queue" in result["imported"]
    assert result["loaded"] == []
