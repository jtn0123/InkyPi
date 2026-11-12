from datetime import datetime
from pathlib import Path
from typing import Any, cast

import pytest
from PIL import Image


def _dummy_plugin(device_config: Any) -> Any:
    class DummyPlugin:
        config: dict[str, list[Any]] = {"image_settings": []}

        def generate_image(self, settings: Any, cfg: Any) -> Any:
            return Image.new("RGB", cfg.get_resolution(), "white")

        def get_latest_metadata(self) -> Any:
            return {"meta": 1}

    return DummyPlugin()


def test_wait_for_trigger_returns_manual_refresh(
    device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from display.display_manager import DisplayManager
    from refresh_task import ManualRefresh, ManualUpdateRequest, RefreshTask

    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)
    task.running = True
    monkeypatch.setattr(task.condition, "wait", lambda timeout=None: None)

    manual = ManualRefresh("dummy", {})
    request = ManualUpdateRequest("req-1", manual)
    task.manual_update_requests.append(request)
    trigger = task._wait_for_trigger()
    assert trigger is not None
    pm, latest, dt, queued = trigger
    assert queued is request
    assert not task.manual_update_requests


def test_select_refresh_action_playlist(
    device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> Any:
    from display.display_manager import DisplayManager
    from refresh_task import PlaylistRefresh, RefreshTask

    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)

    class FakePlaylist:
        name = "pl"

    class FakePlugin:
        plugin_id = "dummy"
        name = "inst"
        settings: dict[str, Any] = {}

        def get_image_path(self) -> Any:
            return "dummy.png"

        def should_refresh(self, dt: Any) -> Any:
            return True

    fake_playlist = FakePlaylist()
    fake_plugin = FakePlugin()

    def fake_determine(self: Any, pm: Any, latest: Any, current_dt: Any) -> Any:
        return fake_playlist, fake_plugin

    monkeypatch.setattr(
        task, "_determine_next_plugin", fake_determine.__get__(task, RefreshTask)
    )
    action, request_id = task._select_refresh_action(
        None, None, task._get_current_datetime(), None
    )
    assert request_id is None
    assert isinstance(action, PlaylistRefresh)
    assert action.playlist is fake_playlist
    assert action.plugin_instance is cast(Any, fake_plugin)


@pytest.mark.parametrize(
    "next_plugin", [(None, None), ("playlist-without-due-plugin", None)]
)
def test_select_refresh_action_nothing_due(
    device_config_dev: Any, monkeypatch: pytest.MonkeyPatch, next_plugin: Any
) -> None:
    """A scheduled check with no eligible playlist/plugin selects no action."""
    from display.display_manager import DisplayManager
    from refresh_task import RefreshTask

    task = RefreshTask(device_config_dev, DisplayManager(device_config_dev))
    monkeypatch.setattr(
        task, "_determine_next_plugin", lambda pm, latest, current_dt: next_plugin
    )

    action, request_id = task._select_refresh_action(
        None, None, task._get_current_datetime(), None
    )

    assert action is None
    assert request_id is None


def test_run_scheduled_tick_with_nothing_due_skips_refresh(
    device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When no plugin is due, the loop still ticks but never renders."""
    from display.display_manager import DisplayManager
    from refresh_task import RefreshTask

    task = RefreshTask(device_config_dev, DisplayManager(device_config_dev))
    triggers = iter([("pm", "latest", task._get_current_datetime(), None), None])
    monkeypatch.setattr(task, "_wait_for_trigger", lambda: next(triggers))
    monkeypatch.setattr(
        task, "_determine_next_plugin", lambda pm, latest, current_dt: (None, None)
    )

    def _unexpected_refresh(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("no refresh should run when nothing is due")

    monkeypatch.setattr(task, "_perform_refresh", _unexpected_refresh)
    monkeypatch.setattr(task, "_update_refresh_info", _unexpected_refresh)
    cleanup_ticks: list[int] = []
    monkeypatch.setattr(
        task,
        "_maybe_run_history_cleanup",
        lambda: cleanup_ticks.append(task._tick_count),
    )

    task._run()  # returns once _wait_for_trigger yields None

    assert task._tick_count == 1
    assert cleanup_ticks == [1]
    assert task._work_started_at is None


def test_select_refresh_action_manual(device_config_dev: Any) -> None:
    from display.display_manager import DisplayManager
    from refresh_task import ManualRefresh, ManualUpdateRequest, RefreshTask

    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)
    manual = ManualRefresh("dummy", {})
    action, request_id = task._select_refresh_action(
        None,
        None,
        task._get_current_datetime(),
        ManualUpdateRequest("req-1", manual),
    )
    assert action is manual
    assert request_id == "req-1"


def test_perform_refresh_skips_when_cached(
    device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from display.display_manager import DisplayManager
    from model import RefreshInfo
    from refresh_task import ManualRefresh, RefreshTask

    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)

    dummy_cfg = {"id": "dummy", "class": "Dummy"}
    monkeypatch.setattr(device_config_dev, "get_plugin", lambda pid: dummy_cfg)
    monkeypatch.setattr(
        "refresh_task.plugin_lookup.get_plugin_instance",
        lambda cfg: _dummy_plugin(device_config_dev),
        raising=True,
    )
    monkeypatch.setattr(
        "refresh_task.refresh_cycle.compute_image_hash",
        lambda img: "same",
        raising=True,
    )

    called = {"val": False}
    monkeypatch.setattr(
        dm, "display_image", lambda *a, **k: called.__setitem__("val", True)
    )

    latest = RefreshInfo("Manual Update", "dummy", "2020-01-01T00:00:00", "same")
    action = ManualRefresh("dummy", {})
    info, used_cached, metrics = task._perform_refresh(
        action, latest, task._get_current_datetime()
    )
    assert used_cached is True
    assert not called["val"]
    assert info is not None
    assert info["image_hash"] == "same"


def test_update_refresh_info_persists(
    device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from display.display_manager import DisplayManager
    from refresh_task import RefreshTask

    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)

    called = {"val": False}
    monkeypatch.setattr(
        device_config_dev, "write_config", lambda: called.__setitem__("val", True)
    )

    refresh_info = {
        "refresh_type": "Manual Update",
        "plugin_id": "dummy",
        "refresh_time": "2020-01-01T00:00:00",
        "image_hash": "abc",
    }
    metrics = {"request_ms": 1, "display_ms": 2, "generate_ms": 3, "preprocess_ms": 4}
    task._update_refresh_info(refresh_info, metrics, used_cached=False)
    ri = device_config_dev.refresh_info
    assert ri.image_hash == "abc"
    assert ri.used_cached is False
    assert called["val"]


def test_update_plugin_health_tracks_retained_display(device_config_dev: Any) -> None:
    from display.display_manager import DisplayManager
    from refresh_task import RefreshTask

    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)

    task._update_plugin_health(
        plugin_id="dummy",
        instance="inst",
        ok=False,
        metrics={"retained_display": True},
        error="timed out",
    )

    snapshot = task.get_health_snapshot()
    assert snapshot["dummy"]["retained_display"] is True
    assert snapshot["dummy"]["timeout_count"] == 1
    assert datetime.fromisoformat(snapshot["dummy"]["last_seen"]).tzinfo is not None


def test_stale_display_path_prefers_processed_image(
    device_config_dev: Any, tmp_path: Path
) -> None:
    from display.display_manager import DisplayManager
    from refresh_task import RefreshTask

    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)

    processed = tmp_path / "processed.png"
    processed.write_bytes(b"x")
    current = tmp_path / "current.png"
    current.write_bytes(b"y")
    device_config_dev.processed_image_file = str(processed)
    device_config_dev.current_image_file = str(current)

    assert task._stale_display_path() == str(processed)


class _StubAction:
    """Minimal refresh action: just what the loop reads before rendering."""

    def get_plugin_id(self) -> str:
        return "clock"

    def get_refresh_info(self) -> dict[str, Any]:
        return {"plugin_instance": "Clock"}


def _loop_task(
    device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> tuple[Any, list[dict[str, Any]]]:
    """A RefreshTask whose loop can be driven one trigger at a time."""
    import contextlib

    import refresh_task.task as task_mod
    from display.display_manager import DisplayManager
    from refresh_task import RefreshTask

    task = RefreshTask(device_config_dev, DisplayManager(device_config_dev))
    monkeypatch.setattr(
        task_mod.crash_breadcrumb,
        "trail",
        lambda *args, **kwargs: contextlib.nullcontext(),
    )
    monkeypatch.setattr(task, "_maybe_run_history_cleanup", lambda: None)
    completed: list[dict[str, Any]] = []
    monkeypatch.setattr(
        task,
        "_complete_manual_request",
        lambda request, **kwargs: completed.append({"request": request, **kwargs}),
    )
    return task, completed


def test_run_refresh_without_image_keeps_previous_refresh_info(
    device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refresh that yields no frame must not overwrite the last-refresh record."""
    task, completed = _loop_task(device_config_dev, monkeypatch)
    triggers = iter([("pm", "latest", task._get_current_datetime(), None), None])
    monkeypatch.setattr(task, "_wait_for_trigger", lambda: next(triggers))
    monkeypatch.setattr(
        task, "_select_refresh_action", lambda *args: (_StubAction(), "req-1")
    )
    metrics = {"no_image": True}
    monkeypatch.setattr(
        task, "_perform_refresh", lambda *args, **kwargs: (None, False, metrics)
    )

    def _unexpected_update(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("refresh info must not be updated without a frame")

    monkeypatch.setattr(task, "_update_refresh_info", _unexpected_update)

    task._run()

    assert completed == [{"request": None, "metrics": metrics}]
    assert task._tick_count == 1
    assert task._work_started_at is None


def test_run_survives_failure_before_a_trigger_arrives(
    device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An error while waiting has no request to fail; the loop just carries on."""
    task, completed = _loop_task(device_config_dev, monkeypatch)
    calls = 0

    def _flaky_wait() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("config briefly unreadable")
        return

    monkeypatch.setattr(task, "_wait_for_trigger", _flaky_wait)

    task._run()

    assert calls == 2
    assert completed == []
    assert task._tick_count == 0


def test_examine_previous_boot_quarantines_crashed_plugin(
    device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import refresh_task.task as task_mod

    task, _completed = _loop_task(device_config_dev, monkeypatch)
    breadcrumb = object()
    monkeypatch.setattr(task_mod.crash_breadcrumb, "examine_boot", lambda: breadcrumb)
    quarantined: list[Any] = []
    monkeypatch.setattr(
        task.health_tracker, "quarantine_after_crash", quarantined.append
    )

    task._examine_previous_boot()

    assert quarantined == [breadcrumb]


def test_examine_previous_boot_never_blocks_startup(
    device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Neither a broken breadcrumb nor a failed quarantine may raise."""
    import refresh_task.task as task_mod

    task, _completed = _loop_task(device_config_dev, monkeypatch)
    quarantined: list[Any] = []

    def _broken_examine() -> Any:
        raise OSError("breadcrumb unreadable")

    monkeypatch.setattr(task_mod.crash_breadcrumb, "examine_boot", _broken_examine)
    monkeypatch.setattr(
        task.health_tracker, "quarantine_after_crash", quarantined.append
    )
    task._examine_previous_boot()
    assert quarantined == []

    def _broken_quarantine(breadcrumb: Any) -> None:
        quarantined.append(breadcrumb)
        raise RuntimeError("health store locked")

    monkeypatch.setattr(task_mod.crash_breadcrumb, "examine_boot", lambda: "crumb")
    monkeypatch.setattr(
        task.health_tracker, "quarantine_after_crash", _broken_quarantine
    )
    task._examine_previous_boot()
    assert quarantined == ["crumb"]
