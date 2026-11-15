"""A worker hands the parent the plugin's cache file instead of re-encoding.

PlaylistRefresh already saves the rendered image as the plugin's cache PNG
(and the not-due path returns that file's contents), so encoding it again
into a tempfile cost the Pi an extra PNG encode and write per refresh. The
parent must read that file but never delete it: the next not-due turn
loads it.
"""

from __future__ import annotations

import glob
import os
import queue
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from PIL import Image

from model import PluginInstance
from refresh_task import PlaylistRefresh
from refresh_task.actions import RefreshAction
from refresh_task.executor import RefreshExecutor

NOW = datetime(2025, 1, 1, 12, 30, tzinfo=UTC)


class _Playlist:
    name = "Default"


class _Plugin:
    config: dict[str, Any] = {"image_settings": []}

    def __init__(self, image: Image.Image | None) -> None:
        self.image = image

    def generate_image(self, settings: Any, device_config: Any) -> Image.Image | None:
        return self.image


def _instance() -> PluginInstance:
    return PluginInstance(
        plugin_id="ai_text",
        name="handoff",
        settings={"title": "T"},
        refresh={"interval": 1},
    )


def _cache_path(device_config: Any, instance: PluginInstance) -> str:
    return os.path.join(device_config.plugin_image_dir, instance.get_image_path())


def test_due_refresh_records_the_cache_file_it_wrote(device_config_dev: Any) -> None:
    instance = _instance()
    action = PlaylistRefresh(_Playlist(), instance, force=True)
    image = action.execute(
        _Plugin(Image.new("RGB", (40, 30), "red")), device_config_dev, NOW
    )

    assert image is not None
    path = _cache_path(device_config_dev, instance)
    assert action.cached_image_path == path
    with Image.open(path) as cached:
        assert cached.tobytes() == image.tobytes()


def test_not_due_refresh_records_the_cache_file_it_read(
    device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance = _instance()
    path = _cache_path(device_config_dev, instance)
    Image.new("RGB", (40, 30), "blue").save(path)
    monkeypatch.setattr(instance, "should_refresh", lambda _dt: False)
    action = PlaylistRefresh(_Playlist(), instance, force=False)

    image = action.execute(_Plugin(None), device_config_dev, NOW)

    assert image is not None and image.getpixel((0, 0)) == (0, 0, 255)
    assert action.cached_image_path == path


def test_no_image_leaves_no_cache_path(device_config_dev: Any) -> None:
    action = PlaylistRefresh(_Playlist(), _instance(), force=True)
    action.cached_image_path = "/stale/from/an/earlier/turn.png"
    assert action.execute(_Plugin(None), device_config_dev, NOW) is None
    assert action.cached_image_path is None


class _Action(RefreshAction):
    """A refresh action that may report a cache file, like PlaylistRefresh."""

    def __init__(self, cached_image_path: str | None) -> None:
        self.cached_image_path = cached_image_path

    def execute(self, plugin: Any, device_config: Any, current_dt: Any) -> Any:
        return plugin.generate_image(None, device_config)


def _run_worker(action: _Action, device_config: Any, image: Image.Image) -> Any:
    from refresh_task import _execute_refresh_attempt_worker

    result_queue: queue.Queue[Any] = queue.Queue()
    with (
        patch("refresh_task.worker.get_plugin_instance", return_value=_Plugin(image)),
        patch("refresh_task.worker._restore_child_config", return_value=device_config),
    ):
        _execute_refresh_attempt_worker(
            result_queue, {"id": "handoff"}, action, device_config, NOW
        )
    return result_queue.get_nowait()


def _render_tempfiles(directory: Path) -> list[str]:
    return glob.glob(str(directory / "inkypi_render_*.png"))


def test_worker_hands_over_the_cache_file_without_encoding(
    device_config_dev: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    cache = tmp_path / "plugin.png"
    image = Image.new("RGB", (40, 30), "green")
    image.save(cache)

    payload = _run_worker(_Action(str(cache)), device_config_dev, image)

    assert payload["ok"] is True
    assert payload["image_path"] == str(cache)
    assert payload["image_path_owned"] is False
    assert _render_tempfiles(tmp_path) == []


def test_worker_falls_back_to_a_tempfile_when_the_cache_is_gone(
    device_config_dev: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    image = Image.new("RGB", (40, 30), "green")

    payload = _run_worker(
        _Action(str(tmp_path / "missing.png")), device_config_dev, image
    )

    assert payload["ok"] is True
    assert payload.get("image_path_owned", True) is True
    assert _render_tempfiles(tmp_path) == [payload["image_path"]]
    os.unlink(payload["image_path"])


class _ExitedProc:
    exitcode = 0


@pytest.mark.parametrize(
    ("owned", "kept"),
    [(False, True), (True, False), (None, False)],
    ids=["cache-file", "tempfile", "legacy-payload"],
)
def test_parent_deletes_only_files_it_owns(
    tmp_path: Path, owned: bool | None, kept: bool
) -> None:
    path = tmp_path / "frame.png"
    Image.new("RGB", (20, 10), "red").save(path)
    payload: dict[str, Any] = {"ok": True, "image_path": str(path)}
    if owned is not None:
        payload["image_path_owned"] = owned
    result_queue: queue.Queue[Any] = queue.Queue()
    result_queue.put(payload)

    image, _meta = RefreshExecutor.handle_process_result_payload(
        result_queue, _ExitedProc(), "handoff", 1
    )

    assert image is not None and image.size == (20, 10)
    assert path.exists() is kept
