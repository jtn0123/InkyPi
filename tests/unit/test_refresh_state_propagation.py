# pyright: reportMissingImports=false
"""Plugin-instance state produced by a refresh must reach the parent process.

``PlaylistRefresh.execute`` advances ``latest_refresh_time`` on the plugin
instance it was handed.  In the default ``process`` isolation mode that
instance is the child's copy, so unless the worker reports the change back the
parent never sees it: ``should_refresh()`` stays true and every playlist turn
re-renders instead of reusing the cached plugin image.

``tests/conftest.py`` forces ``INKYPI_PLUGIN_ISOLATION=none`` for speed, which
is exactly why this went unnoticed — these tests opt back into real child
processes.
"""

from __future__ import annotations

import json
import multiprocessing
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from PIL import Image

import refresh_task.task as task_mod
import refresh_task.worker as worker_mod
from model import PluginInstance, RefreshInfo
from refresh_task import RefreshTask
from refresh_task.actions import PlaylistRefresh

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="fork start method is POSIX-only"
)

_PLUGIN_ID = "counting_plugin"


class _CountingPlugin:
    """Appends a line to ``settings['marker']`` for every render.

    The marker file is the only reliable way to count renders that happen in
    a child process.
    """

    def __init__(self, produce_image: bool = True) -> None:
        self.produce_image = produce_image

    def generate_image(self, settings: Any, device_config: Any) -> Any:
        with open(settings["marker"], "a", encoding="utf-8") as fh:
            fh.write("render\n")
        # Mirrors image_upload, which writes its rotating index back here.
        settings["image_index"] = settings.get("image_index", 0) + 1
        if not self.produce_image:
            return None
        return Image.new("RGB", (800, 480), "white")

    def skip_display_condition(self, *_args: Any) -> None:
        return None


def _render_count(marker: Path) -> int:
    if not marker.exists():
        return 0
    return len(marker.read_text(encoding="utf-8").splitlines())


def _setup(
    device_config_dev: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    produce_image: bool = True,
) -> tuple[RefreshTask, Any, PluginInstance, Path]:
    monkeypatch.setenv("INKYPI_PLUGIN_ISOLATION", "process")
    monkeypatch.setenv("INKYPI_PLUGIN_RETRY_MAX", "0")
    # ``fork`` so the child inherits the monkeypatched plugin factory below;
    # production prefers forkserver on Linux, which only changes how the
    # arguments travel, not what the worker sends back.
    monkeypatch.setattr(
        task_mod, "_get_mp_context", lambda: multiprocessing.get_context("fork")
    )
    plugin_factory = lambda _cfg: _CountingPlugin(produce_image)  # noqa: E731
    monkeypatch.setattr(worker_mod, "get_plugin_instance", plugin_factory)
    monkeypatch.setattr(worker_mod, "load_plugins", lambda _plugins: None)
    monkeypatch.setattr(task_mod, "get_plugin_instance", plugin_factory)
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
    task = RefreshTask(device_config_dev, display_manager)
    return task, playlist, instance, marker


def _persisted_refresh_time(device_config_dev: Any) -> Any:
    with open(device_config_dev.config_file, encoding="utf-8") as fh:
        data = json.load(fh)
    for playlist in data["playlist_config"]["playlists"]:
        for plugin in playlist["plugins"]:
            if plugin["plugin_id"] == _PLUGIN_ID:
                return plugin.get("latest_refresh_time")
    raise AssertionError("plugin instance missing from persisted config")


def _empty_refresh_info() -> RefreshInfo:
    return RefreshInfo(
        refresh_type="Manual Update",
        plugin_id="",
        refresh_time=None,
        image_hash=None,
    )


def test_process_isolation_propagates_refresh_time_to_parent(
    device_config_dev: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    task, playlist, instance, marker = _setup(device_config_dev, monkeypatch, tmp_path)
    first = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)

    refresh_info, used_cached, metrics = task._perform_refresh(
        PlaylistRefresh(playlist, instance), _empty_refresh_info(), first
    )

    assert _render_count(marker) == 1
    assert instance.latest_refresh_time == first.isoformat()
    # The end-of-cycle refresh-info write, as in RefreshTask._run, is what
    # carries the committed timestamp to disk.
    assert refresh_info is not None
    task._update_refresh_info(refresh_info, metrics, used_cached)
    assert _persisted_refresh_time(device_config_dev) == first.isoformat()


def test_process_isolation_second_cycle_reuses_cached_image(
    device_config_dev: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    task, playlist, instance, marker = _setup(device_config_dev, monkeypatch, tmp_path)
    first = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)

    task._perform_refresh(
        PlaylistRefresh(playlist, instance), _empty_refresh_info(), first
    )
    # Interval is an hour; ten minutes later the cached image must be reused.
    task._perform_refresh(
        PlaylistRefresh(playlist, instance),
        _empty_refresh_info(),
        first + timedelta(minutes=10),
    )

    assert _render_count(marker) == 1, "second cycle must not regenerate"
    assert instance.latest_refresh_time == first.isoformat()


def test_process_isolation_control_only_plugin_advances_refresh_time(
    device_config_dev: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A plugin that deliberately renders nothing is a success, not a failure."""
    task, playlist, instance, marker = _setup(
        device_config_dev, monkeypatch, tmp_path, produce_image=False
    )
    first = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)

    refresh_info, _used_cached, metrics = task._perform_refresh(
        PlaylistRefresh(playlist, instance), _empty_refresh_info(), first
    )

    assert refresh_info is None
    assert metrics.get("no_image") is True
    assert _render_count(marker) == 1
    assert instance.latest_refresh_time == first.isoformat()
    assert _persisted_refresh_time(device_config_dev) == first.isoformat()
    assert instance.consecutive_failure_count == 0


def test_process_isolation_propagates_settings_written_by_plugin(
    device_config_dev: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A slideshow-style index written into settings must survive the child."""
    task, playlist, instance, marker = _setup(device_config_dev, monkeypatch, tmp_path)
    first = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)

    for offset in range(2):
        task._perform_refresh(
            PlaylistRefresh(playlist, instance, force=True),
            _empty_refresh_info(),
            first + timedelta(minutes=offset),
        )

    assert _render_count(marker) == 2
    assert instance.settings["image_index"] == 2
    assert instance.settings["marker"] == str(marker)


def test_inprocess_isolation_behaves_identically(
    device_config_dev: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    task, playlist, instance, marker = _setup(device_config_dev, monkeypatch, tmp_path)
    monkeypatch.setenv("INKYPI_PLUGIN_ISOLATION", "none")
    first = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)

    for offset in (0, 10):
        task._perform_refresh(
            PlaylistRefresh(playlist, instance),
            _empty_refresh_info(),
            first + timedelta(minutes=offset),
        )

    assert _render_count(marker) == 1
    assert instance.latest_refresh_time == first.isoformat()
    assert instance.settings["image_index"] == 1
