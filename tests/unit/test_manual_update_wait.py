"""How long "Update display" waits, and what happens when the wait ends.

The wait used to be one plugin time limit long while the loop allows two
attempts, so a slow render that was retried looked like a timeout even when
the display then updated. Giving up also recorded a plugin failure for a
render that was still running, or had never started. A render stopped at its
time limit was retried, which for an AI image means paying for a second one.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from flask.testing import FlaskClient
from PIL import Image

from refresh_task import ManualRefresh, RefreshTask
from refresh_task.executor import RefreshExecutor
from utils.domain_errors import RefreshLoopBusy

_WAIT_ENV = (
    "INKYPI_MANUAL_UPDATE_WAIT_S",
    "INKYPI_MANUAL_UPDATE_WAIT_S_CLOCK",
    "INKYPI_MANUAL_UPDATE_WAIT_S_AI_IMAGE",
    "INKYPI_PLUGIN_TIMEOUT_S",
    "INKYPI_PLUGIN_TIMEOUT_S_CLOCK",
    "INKYPI_PLUGIN_TIMEOUT_S_AI_IMAGE",
    "INKYPI_PLUGIN_RETRY_MAX",
    "INKYPI_PLUGIN_RETRY_BACKOFF_MS",
)


@pytest.fixture
def task(monkeypatch: pytest.MonkeyPatch) -> Iterator[RefreshTask]:
    """A task that accepts requests, with no loop thread: tests play the loop."""
    for key in _WAIT_ENV:
        monkeypatch.delenv(key, raising=False)
    device_config = MagicMock()
    device_config.get_plugins.return_value = []
    refresh_task = RefreshTask(device_config, MagicMock())
    refresh_task.running = True
    yield refresh_task
    refresh_task.running = False


def _play_loop(
    task: RefreshTask,
    *,
    mark_started: bool,
    finish_after_s: float | None,
) -> threading.Thread:
    """Take the next request off the queue, then maybe finish it later."""

    def run() -> None:
        deadline = time.monotonic() + 5
        while not task.manual_update_requests and time.monotonic() < deadline:
            time.sleep(0.005)
        with task.condition:
            request = task.manual_update_requests.popleft()
        if mark_started:
            request.started.set()
        if finish_after_s is not None:
            time.sleep(finish_after_s)
            task._complete_manual_request(request, metrics={"finished": True})

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


@pytest.mark.parametrize("plugin_id", ["clock", "ai_image"])
@pytest.mark.parametrize("retry_max", [None, "2"])
def test_wait_covers_every_attempt_the_loop_may_make(
    task: RefreshTask,
    monkeypatch: pytest.MonkeyPatch,
    plugin_id: str,
    retry_max: str | None,
) -> None:
    if retry_max is not None:
        monkeypatch.setenv("INKYPI_PLUGIN_RETRY_MAX", retry_max)
    _retries, backoff_ms, attempts = RefreshExecutor.retry_policy()
    render_s = (
        attempts * RefreshTask._plugin_timeout_seconds(plugin_id)
        + (attempts - 1) * backoff_ms / 1000.0
    )

    assert RefreshTask._manual_update_wait_seconds(plugin_id) > render_s


def test_request_the_loop_never_takes_is_withdrawn_as_busy(
    task: RefreshTask, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INKYPI_MANUAL_UPDATE_WAIT_S", "0.05")

    with pytest.raises(RefreshLoopBusy):
        task.manual_update(ManualRefresh("clock", {}))

    assert not task.manual_update_requests, "a withdrawn request must not run later"
    assert task.plugin_health == {}, "a render that never ran did not fail"


def test_render_still_running_times_out_without_recording_a_failure(
    task: RefreshTask, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INKYPI_MANUAL_UPDATE_WAIT_S", "0.1")
    _play_loop(task, mark_started=True, finish_after_s=None)

    with pytest.raises(TimeoutError, match="timed out after"):
        task.manual_update(ManualRefresh("clock", {}))

    # The render records its own outcome when it ends.
    assert task.plugin_health == {}


def test_request_taken_just_as_the_first_wait_ends_still_returns_its_result(
    task: RefreshTask, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The loop has it, so it will run: wait for the result, don't call it busy."""
    monkeypatch.setenv("INKYPI_MANUAL_UPDATE_WAIT_S", "0.2")
    _play_loop(task, mark_started=False, finish_after_s=0.3)

    assert task.manual_update(ManualRefresh("clock", {})) == {"finished": True}


def test_stopping_the_loop_ends_the_wait_at_once(
    task: RefreshTask, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INKYPI_MANUAL_UPDATE_WAIT_S", "5")
    outcome: dict[str, BaseException] = {}

    def wait() -> None:
        try:
            task.manual_update(ManualRefresh("clock", {}))
        except BaseException as exc:  # recorded for the assertion below
            outcome["error"] = exc

    waiter = threading.Thread(target=wait, daemon=True)
    waiter.start()
    deadline = time.monotonic() + 2
    while not task.manual_update_requests and time.monotonic() < deadline:
        time.sleep(0.005)
    task.stop()
    waiter.join(timeout=2)

    assert not waiter.is_alive(), "the caller sat out its whole wait"
    assert isinstance(outcome.get("error"), RuntimeError)
    assert "stopped" in str(outcome["error"])


class _HungProcess:
    """A worker process that never finishes, so every attempt hits its limit."""

    pid = 0
    exitcode = None

    def __init__(self, started: list[object]) -> None:
        self._started = started
        self._alive = True

    def start(self) -> None:
        self._started.append(self)

    def join(self, timeout: float | None = None) -> None:
        return None

    def is_alive(self) -> bool:
        return self._alive

    def terminate(self) -> None:
        self._alive = False

    def kill(self) -> None:
        self._alive = False


def test_render_stopped_at_its_time_limit_is_not_retried(
    task: RefreshTask, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An AI image that ran out of time would be generated, and billed, again."""
    started: list[object] = []
    context = MagicMock()
    context.Process.side_effect = lambda *a, **k: _HungProcess(started)
    task.executor.mp_context_factory = lambda: context
    # Keep cleanup away from real process groups.
    monkeypatch.delattr(os, "getpgid", raising=False)
    action = MagicMock()
    action.get_plugin_id.return_value = "ai_image"

    with (
        patch.dict(
            os.environ,
            {
                "INKYPI_PLUGIN_ISOLATION": "process",
                "INKYPI_PLUGIN_RETRY_MAX": "3",
                "INKYPI_PLUGIN_RETRY_BACKOFF_MS": "1",
            },
        ),
        pytest.raises(TimeoutError, match="timed out after"),
    ):
        task.executor.execute_with_policy(action, {"id": "ai"}, datetime.now(UTC))

    assert len(started) == 1


def test_timeout_raised_inside_the_plugin_is_still_retried(
    task: RefreshTask,
) -> None:
    """A slow socket is a passing hiccup, not a render that used up its time."""
    calls: list[int] = []
    image = Image.new("RGB", (4, 4), "white")

    def attempt(*_args: Any) -> tuple[Any, Any]:
        calls.append(1)
        if len(calls) == 1:
            return None, TimeoutError("read timed out")
        return image, None

    action = MagicMock()
    action.get_plugin_id.return_value = "weather"
    with (
        patch.object(task.executor, "run_subprocess_attempt", side_effect=attempt),
        patch.dict(
            os.environ,
            {
                "INKYPI_PLUGIN_ISOLATION": "process",
                "INKYPI_PLUGIN_RETRY_MAX": "1",
                "INKYPI_PLUGIN_RETRY_BACKOFF_MS": "1",
            },
        ),
    ):
        result, _meta = task.executor.execute_with_policy(
            action, {"id": "weather"}, datetime.now(UTC)
        )

    assert result is image
    assert len(calls) == 2


@pytest.mark.parametrize("running", [True, False])
def test_background_update_tells_the_page_how_long_to_wait(
    client: FlaskClient,
    flask_app: Flask,
    monkeypatch: pytest.MonkeyPatch,
    running: bool,
) -> None:
    import blueprints.plugin._update_now as blueprint

    monkeypatch.setenv("INKYPI_MANUAL_UPDATE_WAIT_S", "100")
    monkeypatch.setattr(flask_app.config["REFRESH_TASK"], "running", running)
    queue = MagicMock()
    queue.enqueue.return_value = "j1"
    monkeypatch.setattr(blueprint, "get_job_queue", lambda: queue)

    resp = client.post("/update_now?async=1", data={"plugin_id": "clock"})

    assert resp.status_code == 202
    # One wait for the loop to take it, one for the render. Without the loop
    # the page keeps its own limit.
    expected = {"job_id": "j1", "wait_s": 200.0} if running else {"job_id": "j1"}
    assert resp.get_json() == expected
