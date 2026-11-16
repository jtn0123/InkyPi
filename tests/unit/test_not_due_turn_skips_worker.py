# pyright: reportMissingImports=false
"""A playlist turn that isn't due reloads the last render without a worker (G6).

Such a turn only reads the plugin's cache PNG, yet it still started a worker
process to do it. The parent now reads the file itself and shows it exactly as
the worker's cached turn did: same image, same cache file handed to the
display, same history metadata, and no change to the plugin instance.

These tests opt back into real child processes (``tests/conftest.py`` forces
in-process plugins) and count the processes started.
"""

from __future__ import annotations

import multiprocessing
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from PIL import Image

import refresh_task.plugin_lookup as plugin_lookup_mod
import refresh_task.task as task_mod
import refresh_task.worker as worker_mod
from model import PluginInstance
from refresh_task import RefreshTask
from refresh_task.actions import PlaylistRefresh

pytestmark = [
    pytest.mark.skipif(
        sys.platform == "win32", reason="fork start method is POSIX-only"
    ),
    # Forked on purpose so the child inherits the monkeypatched plugin
    # factory, as in test_refresh_state_propagation.
    pytest.mark.filterwarnings(
        "ignore:This process .* is multi-threaded:DeprecationWarning"
    ),
]

_PLUGIN_ID = "counting_plugin"
FIRST = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
NOT_DUE = FIRST + timedelta(minutes=10)


class _CountingPlugin:
    """Appends a line to ``settings['marker']`` for every render."""

    def generate_image(self, settings: Any, device_config: Any) -> Any:
        with open(settings["marker"], "a", encoding="utf-8") as fh:
            fh.write("render\n")
        return Image.new("RGB", (800, 480), "purple")

    def skip_display_condition(self, *_args: Any) -> None:
        return None


class _CountingContext:
    """A fork context that counts the worker processes it starts."""

    def __init__(self) -> None:
        self._ctx = multiprocessing.get_context("fork")
        self.processes = 0

    def Queue(self, maxsize: int = 0) -> Any:
        return self._ctx.Queue(maxsize=maxsize)

    def Process(self, *args: Any, **kwargs: Any) -> Any:
        self.processes += 1
        return self._ctx.Process(*args, **kwargs)


def _render_count(marker: Path) -> int:
    if not marker.exists():
        return 0
    return len(marker.read_text(encoding="utf-8").splitlines())


def _setup(
    device_config_dev: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[RefreshTask, Any, PluginInstance, Path, MagicMock, _CountingContext]:
    monkeypatch.setenv("INKYPI_PLUGIN_ISOLATION", "process")
    monkeypatch.setenv("INKYPI_PLUGIN_RETRY_MAX", "0")
    ctx = _CountingContext()
    monkeypatch.setattr(task_mod, "_get_mp_context", lambda: ctx)
    plugin_factory = lambda _cfg: _CountingPlugin()  # noqa: E731
    monkeypatch.setattr(worker_mod, "get_plugin_instance", plugin_factory)
    monkeypatch.setattr(worker_mod, "load_plugins", lambda _plugins: None)
    monkeypatch.setattr(plugin_lookup_mod, "get_plugin_instance", plugin_factory)
    plugin_config = {"id": _PLUGIN_ID, "class": "Counting", "image_settings": []}
    monkeypatch.setattr(
        device_config_dev,
        "get_plugin",
        lambda pid: plugin_config if pid == _PLUGIN_ID else None,
    )

    marker = tmp_path / "renders.log"
    instance = PluginInstance(
        plugin_id=_PLUGIN_ID,
        name="inst",
        settings={"marker": str(marker)},
        refresh={"interval": 3600},
    )
    pm = device_config_dev.get_playlist_manager()
    playlist = pm.get_playlist("Default")
    if playlist is None:
        pm.add_default_playlist()
        playlist = pm.get_playlist("Default")
    playlist.plugins.append(instance)
    device_config_dev.write_config()

    display_manager = MagicMock()
    display_manager.display_image.return_value = {"display_ms": 1}
    # Never "already on the panel", so every turn reaches the display.
    display_manager.panel_shows.return_value = False
    task = RefreshTask(device_config_dev, display_manager)
    return task, playlist, instance, marker, display_manager, ctx


def _cache_path(device_config: Any, instance: PluginInstance) -> str:
    return os.path.join(device_config.plugin_image_dir, instance.get_image_path())


def test_a_not_due_turn_starts_no_worker(
    device_config_dev: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    task, playlist, instance, marker, display, ctx = _setup(
        device_config_dev, monkeypatch, tmp_path
    )
    task._perform_refresh(PlaylistRefresh(playlist, instance), FIRST)
    assert ctx.processes == 1

    refresh_info, _used_cached, _metrics = task._perform_refresh(
        PlaylistRefresh(playlist, instance), NOT_DUE
    )

    assert ctx.processes == 1, "a not-due turn must not start a worker"
    assert _render_count(marker) == 1
    assert refresh_info is not None
    assert instance.latest_refresh_time == FIRST.isoformat()
    shown = display.display_image.call_args
    assert shown.kwargs["source_png"] == _cache_path(device_config_dev, instance)
    with Image.open(_cache_path(device_config_dev, instance)) as cached:
        assert shown.args[0].tobytes() == cached.convert("RGB").tobytes()


def test_the_parent_shows_a_not_due_turn_as_the_worker_did(
    device_config_dev: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    task, playlist, instance, marker, display, ctx = _setup(
        device_config_dev, monkeypatch, tmp_path
    )
    task._perform_refresh(PlaylistRefresh(playlist, instance), FIRST)

    # The same turn the old way: the worker loads the cache file.
    with monkeypatch.context() as m:
        m.setattr(PlaylistRefresh, "reuse_cached_image", lambda *_a: None)
        by_worker = task._perform_refresh(PlaylistRefresh(playlist, instance), NOT_DUE)
    worker_call = display.display_image.call_args
    assert ctx.processes == 2

    by_parent = task._perform_refresh(PlaylistRefresh(playlist, instance), NOT_DUE)
    parent_call = display.display_image.call_args
    assert ctx.processes == 2

    assert _render_count(marker) == 1
    assert parent_call.args[0].tobytes() == worker_call.args[0].tobytes()
    assert parent_call.kwargs["source_png"] == worker_call.kwargs["source_png"]
    assert parent_call.kwargs["history_meta"] == worker_call.kwargs["history_meta"]
    assert parent_call.args[1:] == worker_call.args[1:]

    def _without_id(outcome: Any) -> Any:
        info, used_cached, _metrics = outcome
        return {k: v for k, v in info.items() if k != "benchmark_id"}, used_cached

    assert _without_id(by_parent) == _without_id(by_worker)
    assert instance.latest_refresh_time == FIRST.isoformat()
    assert instance.settings == {"marker": str(marker)}


def test_a_due_or_forced_turn_still_renders_in_a_worker(
    device_config_dev: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    task, playlist, instance, marker, _display, ctx = _setup(
        device_config_dev, monkeypatch, tmp_path
    )
    task._perform_refresh(PlaylistRefresh(playlist, instance), FIRST)

    task._perform_refresh(PlaylistRefresh(playlist, instance, force=True), NOT_DUE)
    task._perform_refresh(
        PlaylistRefresh(playlist, instance), FIRST + timedelta(hours=2)
    )

    assert ctx.processes == 3
    assert _render_count(marker) == 3


def test_a_not_due_turn_without_its_cache_file_fails_in_the_worker(
    device_config_dev: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    task, playlist, instance, _marker, _display, ctx = _setup(
        device_config_dev, monkeypatch, tmp_path
    )
    task._perform_refresh(PlaylistRefresh(playlist, instance), FIRST)
    os.remove(_cache_path(device_config_dev, instance))

    with pytest.raises(Exception, match="Failed to load existing plugin image"):
        task._perform_refresh(PlaylistRefresh(playlist, instance), NOT_DUE)

    # As before: the worker tried to read the file, and the turn counts as
    # a failure of this instance.
    assert ctx.processes == 2
    assert instance.consecutive_failure_count == 1
