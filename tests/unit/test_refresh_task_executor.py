from __future__ import annotations

import importlib
import threading
import time
from datetime import UTC, datetime
from types import MethodType
from typing import Any

import pytest
from PIL import Image


class _Recorder:
    def __init__(self) -> None:
        self.steps: list[dict[str, Any]] = []

    def publish_step(self, **kwargs: Any) -> None:
        self.steps.append(kwargs)


class _ZombieOwner:
    _zombie_thread_count = 0
    _zombie_thread_lock = threading.Lock()


class _Action:
    def __init__(self, plugin_id: str = "clock") -> None:
        self.plugin_id = plugin_id

    def get_plugin_id(self) -> str:
        return self.plugin_id

    def execute(self, plugin: Any, device_config: Any, current_dt: datetime) -> Any:
        return plugin.generate_image({}, device_config)


def _make_executor(**kwargs: Any) -> tuple[Any, _Recorder]:
    refresh_executor = importlib.import_module("refresh_task.executor")
    recorder = _Recorder()
    executor = refresh_executor.RefreshExecutor(
        device_config=object(),
        refresh_context=kwargs.get("refresh_context"),
        recorder=recorder,
        plugin_timeout_seconds=lambda _plugin_id: 0.01,
        zombie_owner=_ZombieOwner,
        get_plugin_instance=kwargs.get("get_plugin_instance", lambda _cfg: object()),
    )
    return executor, recorder


def test_executor_policy_retries_transient_subprocess_error(monkeypatch: Any) -> None:
    executor, recorder = _make_executor()
    image = Image.new("RGB", (4, 4), "blue")
    calls = {"count": 0}

    def attempt(
        self: Any,
        refresh_action: Any,
        plugin_config: Any,
        current_dt: datetime,
        plugin_id: str,
        timeout_s: float,
        attempt_number: int,
    ) -> tuple[Any, Any]:
        calls["count"] += 1
        if calls["count"] == 1:
            return None, RuntimeError("temporary")
        return image, {"ok": True}

    monkeypatch.setenv("INKYPI_PLUGIN_ISOLATION", "process")
    monkeypatch.setenv("INKYPI_PLUGIN_RETRY_MAX", "1")
    monkeypatch.setenv("INKYPI_PLUGIN_RETRY_BACKOFF_MS", "0")
    executor.run_subprocess_attempt = MethodType(attempt, executor)

    result, meta = executor.execute_with_policy(
        _Action(), {}, datetime.now(UTC), request_id="req-1"
    )

    assert result is image
    assert meta == {"ok": True}
    assert calls["count"] == 2
    assert recorder.steps == [
        {
            "plugin_id": "clock",
            "request_id": "req-1",
            "step": "retry 1/1",
        }
    ]


def test_executor_policy_skips_retry_for_permanent_error(monkeypatch: Any) -> None:
    executor, _recorder = _make_executor()
    calls = {"count": 0}
    plugin_errors = importlib.import_module("utils.plugin_errors")
    permanent_error = plugin_errors.PermanentPluginError

    def attempt(
        self: Any,
        refresh_action: Any,
        plugin_config: Any,
        current_dt: datetime,
        plugin_id: str,
        timeout_s: float,
        attempt_number: int,
    ) -> tuple[Any, Any]:
        calls["count"] += 1
        return None, permanent_error("bad URL")

    monkeypatch.setenv("INKYPI_PLUGIN_ISOLATION", "process")
    monkeypatch.setenv("INKYPI_PLUGIN_RETRY_MAX", "3")
    executor.run_subprocess_attempt = MethodType(attempt, executor)

    with pytest.raises(permanent_error, match="bad URL"):
        executor.execute_with_policy(_Action(), {}, datetime.now(UTC))

    assert calls["count"] == 1


def test_executor_inprocess_success_returns_image_and_metadata(
    monkeypatch: Any,
) -> None:
    expected = Image.new("RGB", (4, 4), "red")

    class Plugin:
        def generate_image(self, settings: Any, device_config: Any) -> Image.Image:
            return expected

        def get_latest_metadata(self) -> dict[str, str]:
            return {"source": "test"}

    executor, _recorder = _make_executor(get_plugin_instance=lambda _cfg: Plugin())
    monkeypatch.setenv("INKYPI_PLUGIN_RETRY_MAX", "0")

    image, meta = executor.execute_inprocess(_Action(), {}, datetime.now(UTC))

    assert image is expected
    assert meta == {"source": "test"}


def test_executor_inprocess_retry_publishes_request_step(monkeypatch: Any) -> None:
    image = Image.new("RGB", (4, 4), "purple")
    calls = {"count": 0}

    class Plugin:
        def generate_image(self, settings: Any, device_config: Any) -> Image.Image:
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("temporary")
            return image

    executor, recorder = _make_executor(get_plugin_instance=lambda _cfg: Plugin())
    monkeypatch.setenv("INKYPI_PLUGIN_RETRY_MAX", "1")
    monkeypatch.setenv("INKYPI_PLUGIN_RETRY_BACKOFF_MS", "0")

    result, meta = executor.execute_inprocess(
        _Action(), {}, datetime.now(UTC), request_id="req-2"
    )

    assert result is image
    assert meta is None
    assert calls["count"] == 2
    assert recorder.steps == [
        {
            "plugin_id": "clock",
            "request_id": "req-2",
            "step": "retry 1/1",
        }
    ]


def test_executor_thread_timeout_tracks_zombie(monkeypatch: Any) -> None:
    _ZombieOwner._zombie_thread_count = 0
    release = threading.Event()

    class Plugin:
        def generate_image(self, settings: Any, device_config: Any) -> Image.Image:
            release.wait(timeout=5)
            return Image.new("RGB", (4, 4), "green")

    executor, _recorder = _make_executor(get_plugin_instance=lambda _cfg: Plugin())
    monkeypatch.setenv("INKYPI_PLUGIN_RETRY_MAX", "0")

    with pytest.raises(TimeoutError, match="timed out"):
        executor.execute_inprocess(_Action("slow"), {}, datetime.now(UTC))

    assert _ZombieOwner._zombie_thread_count == 1
    release.set()
    deadline = time.monotonic() + 5
    while _ZombieOwner._zombie_thread_count > 0 and time.monotonic() < deadline:
        time.sleep(0.05)
    assert _ZombieOwner._zombie_thread_count == 0
