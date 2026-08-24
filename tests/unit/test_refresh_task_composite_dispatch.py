"""Composite-screen dispatch: task.py/executor.py/worker.py branch on
model.COMPOSITE_PLUGIN_ID to route to CompositeScreenRenderer instead of
plugins.plugin_registry.get_plugin_instance. See composite_render.py and the
"Model & scheduling dispatch" section of the implementation plan.
"""

import queue
import threading
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import patch

import pytest
from PIL import Image

from model import COMPOSITE_PLUGIN_ID, PluginInstance
from refresh_task.actions import RefreshAction

if TYPE_CHECKING:
    from refresh_task.context import RefreshContext
    from refresh_task.recorder import RefreshRecorder


class _Recorder:
    def publish_step(self, **kwargs: Any) -> None:
        pass


def _composite_regions() -> list[dict[str, Any]]:
    return [
        {
            "plugin_id": "fake_a",
            "x": 0,
            "y": 0,
            "w": 800,
            "h": 480,
            "settings": {"color": "red"},
        }
    ]


class _FakeChildPlugin:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    def generate_image(self, settings: Any, device_config: Any) -> Image.Image:
        w, h = device_config.get_resolution()
        return Image.new("RGB", (w, h), settings.get("color", "red"))


class _PlaylistStub:
    name = "Test Playlist"


def _composite_plugin_instance() -> PluginInstance:
    return PluginInstance(
        plugin_id=COMPOSITE_PLUGIN_ID,
        name="My Composite",
        settings={"regions": _composite_regions()},
        refresh={"interval": 3600},
    )


# ---------------------------------------------------------------------------
# task.py guards
# ---------------------------------------------------------------------------


def test_plugin_requires_api_key_is_false_for_composite() -> None:
    from refresh_task.task import _plugin_requires_api_key

    assert _plugin_requires_api_key({"id": COMPOSITE_PLUGIN_ID}) is False


def test_skip_display_reason_short_circuits_for_composite(
    device_config_dev: Any,
) -> None:
    from display.display_manager import DisplayManager
    from refresh_task.actions import PlaylistRefresh
    from refresh_task.task import RefreshTask

    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)
    action = PlaylistRefresh(_PlaylistStub(), _composite_plugin_instance())

    with patch(
        "refresh_task.task.get_plugin_instance",
        side_effect=AssertionError("must not resolve a plugin for a composite screen"),
    ):
        reason = task._skip_display_reason(
            action, {"id": COMPOSITE_PLUGIN_ID}, datetime.now(UTC)
        )

    assert reason is None


def test_perform_refresh_renders_composite_screen(
    device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_perform_refresh must not treat a composite instance as an unknown plugin.

    device_config.get_plugin(COMPOSITE_PLUGIN_ID) legitimately returns None
    (there is no plugins/__composite__/ directory) — _perform_refresh has a
    dedicated branch for this rather than hitting its generic
    "Plugin config not found" early return.
    """
    from display.display_manager import DisplayManager
    from model import RefreshInfo
    from refresh_task.actions import PlaylistRefresh
    from refresh_task.task import RefreshTask

    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)

    monkeypatch.setattr(
        device_config_dev,
        "get_plugin",
        lambda pid: {"id": "fake_a", "class": "FakeA"} if pid == "fake_a" else None,
    )
    monkeypatch.setattr(
        "refresh_task.composite_render.get_plugin_instance",
        lambda cfg: _FakeChildPlugin(cfg),
        raising=True,
    )

    displayed: dict[str, Any] = {}
    monkeypatch.setattr(
        dm,
        "display_image",
        lambda image, **kwargs: displayed.__setitem__("image", image),
    )

    plugin_instance = _composite_plugin_instance()
    action = PlaylistRefresh(_PlaylistStub(), plugin_instance, force=True)
    latest = RefreshInfo("Playlist", COMPOSITE_PLUGIN_ID, None, None)

    info, used_cached, _metrics = task._perform_refresh(
        action, latest, task._get_current_datetime()
    )

    assert info is not None
    assert used_cached is False
    assert "image" in displayed
    assert displayed["image"].size == (800, 480)


# ---------------------------------------------------------------------------
# executor.py — in-process isolation
# ---------------------------------------------------------------------------


class _Action(RefreshAction):
    def __init__(self, plugin_instance: PluginInstance) -> None:
        self.plugin_instance = plugin_instance

    def get_plugin_id(self) -> str:
        return self.plugin_instance.plugin_id

    def execute(self, plugin: Any, device_config: Any, current_dt: datetime) -> Any:
        return plugin.generate_image(self.plugin_instance.settings, device_config)


class _ZombieOwner:
    _zombie_thread_count = 0
    _zombie_thread_lock = threading.Lock()


class _FakeExecutorDeviceConfig:
    def __init__(self, plugin_image_dir: str) -> None:
        self.plugin_image_dir = plugin_image_dir
        self._plugins = {"fake_a": {"id": "fake_a", "class": "FakeA"}}

    def get_resolution(self) -> tuple[int, int]:
        return (800, 480)

    def get_config(self, key: str | None = None, default: Any = None) -> Any:
        if key == "orientation":
            return "horizontal"
        return default

    def load_env_key(self, key: str) -> str | None:
        return None

    def get_plugin(self, plugin_id: str) -> dict[str, Any] | None:
        return self._plugins.get(plugin_id)


def test_executor_inprocess_dispatches_composite_without_plugin_registry(
    tmp_path: Any,
) -> None:
    from refresh_task.executor import RefreshExecutor

    def _must_not_be_called(_cfg: dict[str, Any]) -> Any:
        raise AssertionError("must not resolve a plugin for a composite screen")

    executor = RefreshExecutor(
        device_config=_FakeExecutorDeviceConfig(str(tmp_path)),
        refresh_context=cast("RefreshContext", None),
        recorder=cast("RefreshRecorder", _Recorder()),
        plugin_timeout_seconds=lambda _plugin_id: 5.0,
        zombie_owner=_ZombieOwner,
        get_plugin_instance=_must_not_be_called,
    )

    with patch(
        "refresh_task.composite_render.get_plugin_instance",
        lambda cfg: _FakeChildPlugin(cfg),
    ):
        image, _meta = executor.execute_inprocess(
            _Action(_composite_plugin_instance()),
            {"id": COMPOSITE_PLUGIN_ID},
            datetime.now(UTC),
        )

    assert image.size == (800, 480)


# ---------------------------------------------------------------------------
# worker.py — subprocess-isolation entry point (called in-process, as the
# existing TestExecuteRefreshAttemptWorker tests in
# test_refresh_task_critical.py do)
# ---------------------------------------------------------------------------


def test_worker_entry_point_dispatches_composite_without_plugin_registry(
    device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from refresh_task.worker import _execute_refresh_attempt_worker

    result_queue: queue.Queue[Any] = queue.Queue()

    def _must_not_be_called(_cfg: dict[str, Any]) -> Any:
        raise AssertionError("must not resolve a plugin for a composite screen")

    monkeypatch.setattr(
        device_config_dev,
        "get_plugin",
        lambda pid: {"id": "fake_a", "class": "FakeA"} if pid == "fake_a" else None,
    )

    with (
        patch(
            "refresh_task.worker.get_plugin_instance", side_effect=_must_not_be_called
        ),
        patch(
            "refresh_task.worker._restore_child_config", return_value=device_config_dev
        ),
        patch(
            "refresh_task.composite_render.get_plugin_instance",
            lambda cfg: _FakeChildPlugin(cfg),
        ),
    ):
        _execute_refresh_attempt_worker(
            result_queue,
            {"id": COMPOSITE_PLUGIN_ID},
            _Action(_composite_plugin_instance()),
            device_config_dev,
            datetime.now(UTC),
        )

    payload = result_queue.get_nowait()
    assert payload["ok"] is True
    img = Image.open(payload["image_path"])
    try:
        assert img.size == (800, 480)
    finally:
        img.close()
        import os

        os.unlink(payload["image_path"])
