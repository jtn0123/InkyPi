"""A fresh render's current-image preview is a copy of the plugin's cache PNG.

PlaylistRefresh already wrote the rendered image to the plugin's cache file,
so encoding the same pixels again for ``current_image.png`` cost the Pi an
extra PNG encode per refresh. When the frame is unchanged since that file was
written the display copies its bytes; when fitting to the panel changed the
frame, or there is no cache file, it still encodes.
"""

from __future__ import annotations

import os
import queue
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from PIL import Image, PngImagePlugin

from display.display_manager import DisplayManager
from model import PluginInstance
from refresh_task import PlaylistRefresh, RefreshTask
from refresh_task.executor import RefreshExecutor

NOW = datetime(2025, 1, 1, 12, 30, tzinfo=UTC)


def _png_a_reencode_would_change(path: Path, image: Image.Image) -> bytes:
    """Save *image* so that encoding its pixels again gives different bytes.

    A text chunk and maximum compression are both lost on a re-encode, so
    byte equality with this file proves the preview was copied.
    """
    info = PngImagePlugin.PngInfo()
    info.add_text("source", "plugin-cache")
    image.save(path, format="PNG", compress_level=9, pnginfo=info)
    return path.read_bytes()


def _manager(device_config: Any) -> DisplayManager:
    device_config.update_value("display_type", "mock")
    return DisplayManager(device_config)


def test_display_copies_the_source_png_and_encodes_without_one(
    device_config_dev: Any, tmp_path: Path
) -> None:
    image = Image.new("RGB", device_config_dev.get_resolution(), "red")
    source = tmp_path / "cache.png"
    source_bytes = _png_a_reencode_would_change(source, image)
    dm = _manager(device_config_dev)
    current = Path(device_config_dev.current_image_file)

    dm.display_image(image, source_png=str(source))
    assert current.read_bytes() == source_bytes

    # A different frame with no source file is encoded as before.
    other = Image.new("RGB", device_config_dev.get_resolution(), "white")
    dm.display_image(other)
    assert current.read_bytes() != source_bytes
    with Image.open(current) as saved:
        assert saved.tobytes() == other.tobytes()


@pytest.mark.parametrize("problem", ["missing", "not-png"])
def test_display_encodes_when_the_source_cannot_be_copied(
    device_config_dev: Any, tmp_path: Path, problem: str
) -> None:
    image = Image.new("RGB", device_config_dev.get_resolution(), "blue")
    source = tmp_path / "cache.png"
    if problem == "not-png":
        image.save(source, format="BMP")

    _manager(device_config_dev).display_image(image, source_png=str(source))

    with Image.open(device_config_dev.current_image_file) as saved:
        assert saved.format == "PNG"
        assert saved.tobytes() == image.tobytes()


# --- the refresh task passes the cache file only for an unchanged frame ---


class _Playlist:
    name = "Default"


class _Plugin:
    config: dict[str, Any] = {"image_settings": []}

    def __init__(self, image: Image.Image) -> None:
        self.image = image

    def generate_image(self, settings: Any, device_config: Any) -> Image.Image:
        return self.image

    def get_latest_metadata(self) -> None:
        return None


def _run_playlist_turn(
    device_config: Any, monkeypatch: pytest.MonkeyPatch, image: Image.Image
) -> tuple[list[str | None], str]:
    """Run one in-process playlist refresh; return the source_png values seen."""
    monkeypatch.setenv("INKYPI_PLUGIN_ISOLATION", "none")
    dm = _manager(device_config)
    task = RefreshTask(device_config, dm)
    monkeypatch.setattr(
        device_config, "get_plugin", lambda pid: {"id": pid, "class": "Dummy"}
    )
    monkeypatch.setattr(
        "refresh_task.plugin_lookup.get_plugin_instance", lambda cfg: _Plugin(image)
    )
    seen: list[str | None] = []
    real_display_image = dm.display_image

    def _spy(*args: Any, **kwargs: Any) -> Any:
        seen.append(kwargs.get("source_png"))
        return real_display_image(*args, **kwargs)

    monkeypatch.setattr(dm, "display_image", _spy)
    instance = PluginInstance(
        plugin_id="ai_text", name="copy", settings={}, refresh={"interval": 1}
    )
    action = PlaylistRefresh(_Playlist(), instance, force=True)
    task._perform_refresh(action, NOW)
    return seen, os.path.join(device_config.plugin_image_dir, instance.get_image_path())


def test_refresh_copies_the_cache_file_only_for_an_unchanged_frame(
    device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    width, height = device_config_dev.get_resolution()
    image = Image.new("RGB", (width, height), "green")

    seen, cache_path = _run_playlist_turn(device_config_dev, monkeypatch, image)

    assert seen == [cache_path]
    assert (
        Path(device_config_dev.current_image_file).read_bytes()
        == Path(cache_path).read_bytes()
    )

    # A wrong-size render is fitted to the panel, so the cache file no longer
    # holds the frame being shown: it must be encoded, not copied.
    small = Image.new("RGB", (width // 2, height // 2), "green")
    seen, cache_path = _run_playlist_turn(device_config_dev, monkeypatch, small)

    assert seen == [None]
    with Image.open(device_config_dev.current_image_file) as saved:
        assert saved.size == (width, height)
    with Image.open(cache_path) as cached:
        assert cached.size == (width // 2, height // 2)


class _ExitedProc:
    exitcode = 0


def test_parent_records_which_file_holds_the_worker_image(tmp_path: Path) -> None:
    action = PlaylistRefresh(
        _Playlist(),
        PluginInstance(plugin_id="ai_text", name="w", settings={}, refresh={}),
        force=True,
    )
    for owned in (False, True):
        path = tmp_path / f"frame-{owned}.png"
        Image.new("RGB", (20, 10), "red").save(path)
        result_queue: queue.Queue[Any] = queue.Queue()
        result_queue.put(
            {"ok": True, "image_path": str(path), "image_path_owned": owned}
        )

        RefreshExecutor.handle_process_result_payload(
            result_queue, _ExitedProc(), "ai_text", 1, refresh_action=action
        )

        # The plugin's cache file stays and can be copied; a worker tempfile
        # is deleted once read, so there is nothing to copy.
        assert action.cached_image_path == (None if owned else str(path))
