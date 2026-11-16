"""A broken or missing plugin gets the same answer from every display route.

A plugin's ``RuntimeError`` reached the routes bare from the refresh loop,
and ``route_error_for`` did not know it: ``/update_now`` said 500
``internal_error``, "Display next" 400 "Plugin update failed", the playlist
routes 500, and the direct path (loop stopped) 400 ``plugin_error``. The
refresh cycle and the direct render now both turn it into
``PluginRenderFailed``, mapped once to 400 ``plugin_error``.

An unknown plugin id was 404 with the loop stopped, but 200 "Display updated"
with it running: the loop found no plugin and finished the request with
nothing done. ``/update_now`` now checks before queueing, and the cycle
raises ``PluginNotFound`` for a manual request.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient

from refresh_task import ManualRefresh
from services.job_queue import get_job_queue, reset_job_queue
from utils.backend_errors import PLUGIN_RENDER_FAILED_MSG
from utils.domain_errors import PluginNotFound

_INSTANCE = "Clock Failing"
# Exception text that must never reach a response body.
_SECRET = "/var/lib/inkypi/secret-path: upstream said no"
_MISSING = "not_an_installed_plugin"

# (status, body) where body has at least "code" and "error".
Answer = tuple[int, dict[str, Any]]


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
    device_config_dev.write_config()


def _answer(resp: Any) -> Answer:
    body = resp.get_json()
    assert isinstance(body, dict), resp.get_data(as_text=True)
    return resp.status_code, body


def _update_now_async(client: FlaskClient, plugin_id: str) -> Answer:
    """Queue Update now as the plugin page does, and read the finished job."""
    reset_job_queue()
    try:
        accepted = client.post(
            "/update_now", data={"plugin_id": plugin_id}, headers={"X-Async": "true"}
        )
        if accepted.status_code != 202:
            return _answer(accepted)
        job_id = accepted.get_json()["job_id"]
        get_job_queue().shutdown(wait=True)
        job = client.get(f"/api/job/{job_id}").get_json()
    finally:
        reset_job_queue()
    assert job["status"] == "error", job
    return job["http_status"], job


_ROUTES: dict[str, Callable[[FlaskClient], Answer]] = {
    "update_now": lambda c: _answer(c.post("/update_now", data={"plugin_id": "clock"})),
    "update_now_async": lambda c: _update_now_async(c, "clock"),
    "display-next": lambda c: _answer(c.post("/display-next")),
    "display_next_in_playlist": lambda c: _answer(
        c.post("/display_next_in_playlist", json={"playlist_name": "Default"})
    ),
    "display_plugin_instance": lambda c: _answer(
        c.post(
            "/display_plugin_instance",
            json={
                "playlist_name": "Default",
                "plugin_id": "clock",
                "plugin_instance": _INSTANCE,
            },
        )
    ),
}


@pytest.fixture
def failing_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the clock plugin fail every render, without retries."""
    import plugins.clock.clock as clock_mod

    def boom(self: Any, settings: Any, device_config: Any) -> None:
        raise RuntimeError(_SECRET)

    monkeypatch.setattr(clock_mod.Clock, "generate_image", boom)
    monkeypatch.setenv("INKYPI_PLUGIN_RETRY_MAX", "0")


@pytest.fixture
def running_loop(flask_app: Flask) -> Iterator[Any]:
    task = flask_app.config["REFRESH_TASK"]
    task.start()
    try:
        yield task
    finally:
        task.stop()


def _reset_display_next() -> None:
    import blueprints.main as main

    main._reset_display_next_cooldown()


# The playlist routes have no direct path: with the loop stopped they answer
# 503 refresh_task_unavailable before any render.
_CASES = [(route, "loop") for route in _ROUTES] + [
    ("update_now", "direct"),
    ("update_now_async", "direct"),
    ("display-next", "direct"),
]


@pytest.mark.usefixtures("failing_clock")
@pytest.mark.parametrize(("route", "path"), _CASES, ids=[f"{r}-{p}" for r, p in _CASES])
def test_a_failed_render_gets_the_same_answer_on_every_route(
    request: pytest.FixtureRequest,
    client: FlaskClient,
    flask_app: Flask,
    device_config_dev: Any,
    route: str,
    path: str,
) -> None:
    _seed_default_playlist(device_config_dev)
    if path == "loop":
        request.getfixturevalue("running_loop")
    else:
        flask_app.config["REFRESH_TASK"].running = False
    _reset_display_next()

    status, body = _ROUTES[route](client)
    _reset_display_next()

    assert (status, body.get("code")) == (400, "plugin_error"), body
    assert body["error"] == PLUGIN_RENDER_FAILED_MSG
    assert _SECRET not in str(body)


@pytest.mark.parametrize("path", ["loop", "direct"])
@pytest.mark.parametrize("queued", [False, True], ids=["sync", "async"])
def test_update_now_for_an_unknown_plugin_is_not_found(
    request: pytest.FixtureRequest,
    client: FlaskClient,
    flask_app: Flask,
    path: str,
    queued: bool,
) -> None:
    if path == "loop":
        request.getfixturevalue("running_loop")
    else:
        flask_app.config["REFRESH_TASK"].running = False

    if queued:
        status, body = _update_now_async(client, _MISSING)
    else:
        status, body = _answer(client.post("/update_now", data={"plugin_id": _MISSING}))

    assert (status, body.get("code")) == (404, "plugin_not_found"), body
    assert body["error"] == "Plugin not found"


def test_the_loop_reports_a_manual_request_for_an_unknown_plugin(
    running_loop: Any,
) -> None:
    """The cycle itself raises, for a request that got past the route."""
    with pytest.raises(PluginNotFound):
        running_loop.manual_update(ManualRefresh(_MISSING, {}))


def test_a_scheduled_turn_of_an_unknown_plugin_is_skipped_quietly(
    flask_app: Flask,
) -> None:
    """Only a manual request raises; a scheduled turn is logged and skipped."""
    task = flask_app.config["REFRESH_TASK"]
    outcome = task._perform_refresh(ManualRefresh(_MISSING, {}), datetime.now(UTC))
    assert outcome == (None, False, {})
