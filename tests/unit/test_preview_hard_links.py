"""The preview files are hard links to files already on disk, not copies (G9).

``current_image.png`` held the same bytes as the plugin's cache file, and
``processed_image.png`` the same bytes as the history entry just saved, so
each refresh wrote both pictures to the SD card twice. Every writer of these
files replaces them with a new file, so two names can share one file safely.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from display.display_manager import DisplayManager
from utils.image_utils import link_atomic, save_image_atomic


def _manager(device_config: Any) -> DisplayManager:
    device_config.update_value("display_type", "mock")
    return DisplayManager(device_config)


def _plugin_cache_png(device_config: Any, image: Image.Image) -> Path:
    """Save *image* as an old plugin cache file, like an earlier render."""
    path = Path(device_config.plugin_image_dir) / "clock_Default.png"
    image.save(path, format="PNG")
    os.utime(path, (1_000_000, 1_000_000))
    return path


def _history_pngs(device_config: Any) -> list[Path]:
    return sorted(Path(device_config.history_image_dir).glob("display_*.png"))


def _temp_files(*directories: str | Path) -> list[str]:
    return [
        name
        for directory in directories
        for name in os.listdir(directory)
        if name.endswith(".tmp")
    ]


def test_the_current_image_is_a_fresh_link_to_the_plugin_cache_file(
    device_config_dev: Any,
) -> None:
    image = Image.new("RGB", device_config_dev.get_resolution(), "red")
    source = _plugin_cache_png(device_config_dev, image)
    current = Path(device_config_dev.current_image_file)
    before = time.time() - 1

    _manager(device_config_dev).display_image(image, source_png=str(source))

    assert current.samefile(source)
    # /api/current_image answers If-Modified-Since from this mtime, so the
    # old cache file's time must not show through.
    assert current.stat().st_mtime >= before
    assert _temp_files(current.parent, source.parent) == []


def test_the_processed_image_is_a_link_to_the_new_history_entry(
    device_config_dev: Any,
) -> None:
    image = Image.new("RGB", device_config_dev.get_resolution(), "green")

    _manager(device_config_dev).display_image(image, history_meta={"plugin_id": "x"})

    processed = Path(device_config_dev.processed_image_file)
    [history_png] = _history_pngs(device_config_dev)
    assert processed.samefile(history_png)
    with Image.open(processed) as saved:
        assert saved.convert("RGB").tobytes() == image.tobytes()
    assert _temp_files(processed.parent, history_png.parent) == []


def test_replacing_the_plugin_cache_file_leaves_the_current_image_alone(
    device_config_dev: Any,
) -> None:
    red = Image.new("RGB", device_config_dev.get_resolution(), "red")
    source = _plugin_cache_png(device_config_dev, red)
    _manager(device_config_dev).display_image(red, source_png=str(source))
    current = Path(device_config_dev.current_image_file)
    shown = current.read_bytes()

    # The next render of the plugin replaces its cache file the usual way.
    save_image_atomic(Image.new("RGB", red.size, "blue"), str(source))

    assert current.read_bytes() == shown
    assert not current.samefile(source)


def test_without_hard_links_the_previews_are_copies(
    device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_links(src: str, dst: str) -> None:
        raise OSError(1, "Operation not permitted")

    monkeypatch.setattr(os, "link", no_links)
    image = Image.new("RGB", device_config_dev.get_resolution(), "blue")
    source = _plugin_cache_png(device_config_dev, image)

    _manager(device_config_dev).display_image(
        image, source_png=str(source), history_meta={"plugin_id": "x"}
    )

    current = Path(device_config_dev.current_image_file)
    processed = Path(device_config_dev.processed_image_file)
    [history_png] = _history_pngs(device_config_dev)
    assert current.read_bytes() == source.read_bytes()
    assert not current.samefile(source)
    assert processed.read_bytes() == history_png.read_bytes()
    assert not processed.samefile(history_png)
    assert _temp_files(current.parent, source.parent, history_png.parent) == []


def test_without_history_the_processed_image_is_written(
    device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(device_config_dev, "history_image_dir", None)
    image = Image.new("RGB", device_config_dev.get_resolution(), "white")

    _manager(device_config_dev).display_image(image)

    with Image.open(device_config_dev.processed_image_file) as saved:
        assert saved.convert("RGB").tobytes() == image.tobytes()


class TestLinkAtomic:
    def test_replaces_the_target_with_a_link(self, tmp_path: Path) -> None:
        source = tmp_path / "source.png"
        source.write_bytes(b"new")
        target = tmp_path / "target.png"
        target.write_bytes(b"old")

        link_atomic(str(source), str(target))

        assert target.samefile(source)
        assert target.read_bytes() == b"new"
        assert _temp_files(tmp_path) == []

    def test_linking_a_file_to_itself_leaves_no_temp_name(self, tmp_path: Path) -> None:
        # rename() does nothing when both names are already one file, so the
        # temporary name would be left behind unless it is removed.
        source = tmp_path / "source.png"
        source.write_bytes(b"frame")
        target = tmp_path / "target.png"
        os.link(source, target)

        link_atomic(str(source), str(target), touch=True)

        assert target.samefile(source)
        assert _temp_files(tmp_path) == []

    def test_a_missing_source_raises_and_keeps_the_target(self, tmp_path: Path) -> None:
        target = tmp_path / "target.png"
        target.write_bytes(b"old")

        with pytest.raises(OSError):
            link_atomic(str(tmp_path / "missing.png"), str(target))

        assert target.read_bytes() == b"old"
        assert _temp_files(tmp_path) == []

    def test_a_failed_replace_keeps_the_target_and_removes_the_link(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = tmp_path / "source.png"
        source.write_bytes(b"new")
        target = tmp_path / "target.png"
        target.write_bytes(b"old")

        def boom(src: str, dst: str) -> None:
            raise OSError("EIO")

        monkeypatch.setattr(os, "replace", boom)
        with pytest.raises(OSError, match="EIO"):
            link_atomic(str(source), str(target))

        assert target.read_bytes() == b"old"
        assert _temp_files(tmp_path) == []
