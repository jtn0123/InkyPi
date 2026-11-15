"""Atomic, fast-compressed preview writes and single hashing per refresh (G2)."""

import io
import os
import stat
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

import utils.image_utils as image_utils
from utils.image_utils import (
    FAST_PNG_COMPRESS_LEVEL,
    save_image_atomic,
    write_bytes_atomic,
)


def _leftover_temp_files(directory: str | Path) -> list[str]:
    return [name for name in os.listdir(directory) if name.endswith(".tmp")]


def _failing_save(
    monkeypatch: pytest.MonkeyPatch, should_fail: Any = lambda fp: True
) -> None:
    """Make ``Image.save`` write a partial PNG and then raise, like a crash."""
    real_save = Image.Image.save

    def partial_then_fail(self: Image.Image, fp: Any, *args: Any, **kwargs: Any) -> Any:
        if not should_fail(fp):
            return real_save(self, fp, *args, **kwargs)
        if hasattr(fp, "write"):
            fp.write(b"\x89PNG\r\n\x1a\n truncated")
        else:
            Path(fp).write_bytes(b"\x89PNG\r\n\x1a\n truncated")
        raise OSError("No space left on device")

    monkeypatch.setattr(Image.Image, "save", partial_then_fail)


class TestSaveImageAtomic:
    def test_writes_readable_png(self, tmp_path: Path) -> None:
        target = tmp_path / "current_image.png"
        save_image_atomic(
            Image.new("RGB", (20, 10), "red"),
            str(target),
            format="PNG",
            compress_level=FAST_PNG_COMPRESS_LEVEL,
        )
        with Image.open(target) as img:
            assert img.size == (20, 10)
            assert img.getpixel((0, 0)) == (255, 0, 0)
        assert _leftover_temp_files(tmp_path) == []

    def test_failure_keeps_previous_file_and_cleans_temp(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "processed_image.png"
        Image.new("RGB", (8, 8), "blue").save(target)
        before = target.read_bytes()

        _failing_save(monkeypatch)
        with pytest.raises(OSError, match="No space left"):
            save_image_atomic(Image.new("RGB", (8, 8), "red"), str(target))

        assert target.read_bytes() == before
        assert _leftover_temp_files(tmp_path) == []

    def test_failure_with_no_previous_file_leaves_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _failing_save(monkeypatch)
        with pytest.raises(OSError):
            save_image_atomic(
                Image.new("RGB", (8, 8), "red"), str(tmp_path / "new.png")
            )
        assert os.listdir(tmp_path) == []

    def test_replace_failure_cleans_temp(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "current_image.png"
        Image.new("RGB", (8, 8), "blue").save(target)
        before = target.read_bytes()

        def boom(src: str, dst: str) -> None:
            raise OSError("EIO")

        monkeypatch.setattr(os, "replace", boom)
        with pytest.raises(OSError, match="EIO"):
            save_image_atomic(Image.new("RGB", (8, 8), "red"), str(target))

        assert target.read_bytes() == before
        assert _leftover_temp_files(tmp_path) == []

    def test_preserves_existing_permissions(self, tmp_path: Path) -> None:
        target = tmp_path / "current_image.png"
        Image.new("RGB", (8, 8), "blue").save(target)
        os.chmod(target, 0o640)
        save_image_atomic(Image.new("RGB", (8, 8), "red"), str(target))
        assert stat.S_IMODE(os.stat(target).st_mode) == 0o640

    def test_new_file_is_world_readable(self, tmp_path: Path) -> None:
        # mkstemp creates 0600; the preview must stay readable like before.
        target = tmp_path / "current_image.png"
        save_image_atomic(Image.new("RGB", (8, 8), "red"), str(target))
        assert stat.S_IMODE(os.stat(target).st_mode) == 0o644


class TestWriteBytesAtomic:
    def test_replaces_the_file_and_keeps_its_permissions(self, tmp_path: Path) -> None:
        target = tmp_path / "processed_image.png"
        target.write_bytes(b"old")
        os.chmod(target, 0o640)

        write_bytes_atomic(b"new frame", str(target))

        assert target.read_bytes() == b"new frame"
        assert stat.S_IMODE(os.stat(target).st_mode) == 0o640
        assert _leftover_temp_files(tmp_path) == []

    def test_new_file_is_world_readable(self, tmp_path: Path) -> None:
        target = tmp_path / "current_image.png"
        write_bytes_atomic(b"frame", str(target))
        assert stat.S_IMODE(os.stat(target).st_mode) == 0o644

    def test_replace_failure_keeps_previous_file_and_cleans_temp(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "processed_image.png"
        target.write_bytes(b"old")

        def boom(src: str, dst: str) -> None:
            raise OSError("EIO")

        monkeypatch.setattr(os, "replace", boom)
        with pytest.raises(OSError, match="EIO"):
            write_bytes_atomic(b"new frame", str(target))

        assert target.read_bytes() == b"old"
        assert _leftover_temp_files(tmp_path) == []


class TestDisplayManagerPreviewWrites:
    def test_failed_save_keeps_previous_previews(
        self, device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from display.display_manager import DisplayManager

        dm = DisplayManager(device_config_dev)
        dm.display_image(Image.new("RGB", (800, 480), "blue"))
        current = Path(device_config_dev.current_image_file)
        processed = Path(device_config_dev.processed_image_file)
        current_before = current.read_bytes()
        processed_before = processed.read_bytes()

        # Fail only the preview writes (file objects); history saves by path.
        _failing_save(monkeypatch, should_fail=lambda fp: hasattr(fp, "write"))
        dm.display_image(Image.new("RGB", (800, 480), "red"))

        assert current.read_bytes() == current_before
        assert processed.read_bytes() == processed_before
        with Image.open(processed) as img:
            img.verify()
        assert _leftover_temp_files(current.parent) == []
        assert _leftover_temp_files(processed.parent) == []

    def test_raw_preview_uses_fast_compression(
        self, device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from display.display_manager import DisplayManager

        dm = DisplayManager(device_config_dev)
        seen: list[dict[str, Any]] = []
        real_save = Image.Image.save

        def spy(self: Image.Image, fp: Any, *args: Any, **kwargs: Any) -> Any:
            if hasattr(fp, "write") and not isinstance(fp, io.BytesIO):
                seen.append(kwargs)
            return real_save(self, fp, *args, **kwargs)

        monkeypatch.setattr(Image.Image, "save", spy)
        dm.display_image(Image.new("RGB", (800, 480), "green"))

        assert len(seen) == 1  # current_image; the processed frame is below
        assert seen[0].get("compress_level") == FAST_PNG_COMPRESS_LEVEL
        assert not seen[0].get("optimize")

    def test_processed_frame_is_encoded_once_for_preview_and_history(
        self, device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One encode serves processed_image.png and the history snapshot.

        It uses a fixed zlib level: optimize=True cost ~6 s of CPU per photo
        on a Pi Zero 2 W for a 3% smaller file.
        """
        from display.display_manager import DisplayManager
        from utils.image_utils import HISTORY_PNG_COMPRESS_LEVEL

        dm = DisplayManager(device_config_dev)
        seen: list[dict[str, Any]] = []
        real_save = Image.Image.save

        def spy(self: Image.Image, fp: Any, *args: Any, **kwargs: Any) -> Any:
            if isinstance(fp, io.BytesIO):
                seen.append(kwargs)
            return real_save(self, fp, *args, **kwargs)

        monkeypatch.setattr(Image.Image, "save", spy)
        dm.display_image(Image.new("RGB", (800, 480), "green"))

        assert len(seen) == 1
        assert seen[0].get("compress_level") == HISTORY_PNG_COMPRESS_LEVEL
        assert not seen[0].get("optimize")
        history = list(Path(device_config_dev.history_image_dir).glob("display_*.png"))
        assert len(history) == 1
        processed = Path(device_config_dev.processed_image_file)
        assert history[0].read_bytes() == processed.read_bytes()

    def test_supplied_hash_is_not_recomputed(
        self, device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from display.display_manager import DisplayManager

        dm = DisplayManager(device_config_dev)
        calls = {"n": 0}

        def counting_hash(image: Image.Image) -> str:
            calls["n"] += 1
            return "computed"

        monkeypatch.setattr(image_utils, "compute_image_hash", counting_hash)
        dm.display_image(Image.new("RGB", (800, 480), "red"), image_hash="given")

        assert calls["n"] == 0
        assert dm._last_image_hash == "given"

        dm.display_image(Image.new("RGB", (800, 480), "blue"))
        assert calls["n"] == 1
        assert dm._last_image_hash == "computed"


def test_refresh_hashes_image_once(
    device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A full refresh that pushes to the display hashes the frame exactly once."""
    from display.display_manager import DisplayManager
    from model import RefreshInfo
    from refresh_task import ManualRefresh, RefreshTask

    class DummyPlugin:
        config: dict[str, Any] = {"image_settings": []}

        def generate_image(self, settings: Any, cfg: Any) -> Image.Image:
            return Image.new("RGB", cfg.get_resolution(), "white")

        def get_latest_metadata(self) -> dict[str, Any]:
            return {}

    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)
    monkeypatch.setattr(
        device_config_dev, "get_plugin", lambda pid: {"id": "dummy", "class": "D"}
    )
    monkeypatch.setattr(
        "refresh_task.plugin_lookup.get_plugin_instance", lambda cfg: DummyPlugin()
    )

    real_hash = image_utils.compute_image_hash
    calls = {"n": 0}

    def counting_hash(image: Image.Image) -> str:
        calls["n"] += 1
        return real_hash(image)

    monkeypatch.setattr("refresh_task.refresh_cycle.compute_image_hash", counting_hash)
    monkeypatch.setattr(image_utils, "compute_image_hash", counting_hash)

    latest = RefreshInfo("Manual Update", "dummy", "2020-01-01T00:00:00", "stale")
    info, used_cached, _metrics = task._perform_refresh(
        ManualRefresh("dummy", {}), latest, task._get_current_datetime()
    )

    assert info is not None
    assert used_cached is False
    assert calls["n"] == 1
    assert dm._last_image_hash == info["image_hash"]
