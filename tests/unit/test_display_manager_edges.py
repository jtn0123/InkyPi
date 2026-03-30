# pyright: reportMissingImports=false
"""Edge-case tests for display_manager.py: init errors, prune, save history, hash skip."""

import json
import os
import threading
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from PIL import Image


class TestDisplayManagerInit:
    def test_inky_unavailable_raises(self, device_config_dev, monkeypatch):
        """display_type='inky' with InkyDisplay=None raises RuntimeError."""
        import display.display_manager as dm_mod

        monkeypatch.setattr(dm_mod, "InkyDisplay", None)
        device_config_dev.update_value("display_type", "inky", write=True)

        # Re-read config to pick up change
        import config as config_mod

        cfg = config_mod.Config()
        cfg.update_value("display_type", "inky", write=True)

        with pytest.raises(RuntimeError, match="Inky hardware driver"):
            dm_mod.DisplayManager(cfg)

    def test_waveshare_unavailable_raises(self, device_config_dev, monkeypatch):
        """display_type matching epd pattern with WaveshareDisplay=None raises RuntimeError."""
        import display.display_manager as dm_mod

        monkeypatch.setattr(dm_mod, "WaveshareDisplay", None)

        import config as config_mod

        cfg = config_mod.Config()
        cfg.update_value("display_type", "epd7in5", write=True)

        with pytest.raises(RuntimeError, match="Waveshare driver"):
            dm_mod.DisplayManager(cfg)

    def test_unsupported_display_raises(self, device_config_dev, monkeypatch):
        """Unknown display_type raises ValueError."""
        import display.display_manager as dm_mod
        import config as config_mod

        cfg = config_mod.Config()
        cfg.update_value("display_type", "unknown_display", write=True)

        with pytest.raises(ValueError, match="Unsupported display type"):
            dm_mod.DisplayManager(cfg)


class TestPruneHistory:
    @pytest.fixture(autouse=True)
    def reset_class_state(self):
        """Reset class-level state to avoid leaks between tests."""
        from display.display_manager import DisplayManager

        DisplayManager._history_count_estimate = None
        DisplayManager._history_increment_count = 0
        yield
        DisplayManager._history_count_estimate = None
        DisplayManager._history_increment_count = 0

    def test_skips_when_estimate_under_limit(self, device_config_dev, tmp_path):
        """Estimate below max → no directory scan."""
        from display.display_manager import DisplayManager

        dm = DisplayManager(device_config_dev)
        history_dir = str(tmp_path / "history_prune")
        os.makedirs(history_dir, exist_ok=True)

        # Set estimate well below limit
        dm._history_count_estimate = 10
        dm._history_increment_count = 0

        # Create a file that should NOT be removed
        (tmp_path / "history_prune" / "test.png").write_bytes(b"img")

        dm._prune_history(history_dir)

        # File should still exist (no scan, no prune)
        assert os.path.exists(tmp_path / "history_prune" / "test.png")
        assert dm._history_count_estimate == 11  # incremented

    def test_removes_oldest_over_limit(self, device_config_dev, tmp_path):
        """Files over limit are removed (oldest first), including sidecars."""
        from display.display_manager import DisplayManager

        dm = DisplayManager(device_config_dev)
        history_dir = str(tmp_path / "history_prune2")
        os.makedirs(history_dir, exist_ok=True)

        # Override max entries to a small number
        dm.HISTORY_MAX_ENTRIES = 3

        # Create 5 PNG files with sidecars
        for i in range(5):
            name = f"display_{i:04d}.png"
            sidecar = f"display_{i:04d}.json"
            (tmp_path / "history_prune2" / name).write_bytes(b"img")
            (tmp_path / "history_prune2" / sidecar).write_text("{}")

        # Force a full scan
        dm._history_count_estimate = None

        dm._prune_history(history_dir)

        # Should have 3 remaining (oldest 2 removed)
        remaining = [f for f in os.listdir(history_dir) if f.endswith(".png")]
        assert len(remaining) == 3
        # Oldest (0000, 0001) should be gone
        assert "display_0000.png" not in remaining
        assert "display_0001.png" not in remaining
        # Their sidecars too
        assert not os.path.exists(tmp_path / "history_prune2" / "display_0000.json")
        assert not os.path.exists(tmp_path / "history_prune2" / "display_0001.json")

    def test_recount_forces_scan(self, device_config_dev, tmp_path):
        """After _RECOUNT_INTERVAL increments, a full scan occurs."""
        from display.display_manager import DisplayManager

        dm = DisplayManager(device_config_dev)
        history_dir = str(tmp_path / "history_recount")
        os.makedirs(history_dir, exist_ok=True)

        # Create 2 files
        (tmp_path / "history_recount" / "a.png").write_bytes(b"img")
        (tmp_path / "history_recount" / "b.png").write_bytes(b"img")

        dm._history_count_estimate = 10
        dm._history_increment_count = dm._RECOUNT_INTERVAL  # trigger recount

        dm._prune_history(history_dir)

        # After recount, estimate should match actual count
        assert dm._history_count_estimate == 2

    def test_os_error_handled(self, device_config_dev, tmp_path, monkeypatch):
        """os.listdir raising OSError → no crash."""
        from display.display_manager import DisplayManager

        dm = DisplayManager(device_config_dev)
        dm._history_count_estimate = None  # force scan

        monkeypatch.setattr(os, "listdir", MagicMock(side_effect=OSError("denied")))

        # Should not raise
        dm._prune_history("/nonexistent")


class TestSaveHistoryEntry:
    def test_timestamp_collision(self, device_config_dev, tmp_path):
        """Pre-existing file causes microsecond suffix to be added."""
        from display.display_manager import DisplayManager

        dm = DisplayManager(device_config_dev)
        history_dir = str(tmp_path / "history_collision")
        device_config_dev.history_image_dir = history_dir
        os.makedirs(history_dir, exist_ok=True)

        img = Image.new("RGB", (100, 100), "red")

        # Save first image
        dm._save_history_entry(img)

        # Get the filename that was created
        files_before = set(f for f in os.listdir(history_dir) if f.endswith(".png"))
        assert len(files_before) == 1

        # Save again immediately (same second) - should get suffix
        dm._save_history_entry(img)

        files_after = set(f for f in os.listdir(history_dir) if f.endswith(".png"))
        assert len(files_after) == 2  # both saved, no clobber

    def test_no_history_dir(self, device_config_dev):
        """history_image_dir=None → no-op, no crash."""
        from display.display_manager import DisplayManager

        dm = DisplayManager(device_config_dev)
        device_config_dev.history_image_dir = None

        img = Image.new("RGB", (100, 100), "blue")
        # Should not raise
        dm._save_history_entry(img)

    def test_image_save_failure(self, device_config_dev, tmp_path, monkeypatch):
        """image.save raises OSError → returns early, no sidecar written."""
        from display.display_manager import DisplayManager

        dm = DisplayManager(device_config_dev)
        history_dir = str(tmp_path / "history_fail")
        device_config_dev.history_image_dir = history_dir
        os.makedirs(history_dir, exist_ok=True)

        img = MagicMock()
        img.save.side_effect = OSError("disk full")

        dm._save_history_entry(img, history_meta={"plugin": "test"})

        # No files should be created (save failed, no sidecar)
        json_files = [f for f in os.listdir(history_dir) if f.endswith(".json")]
        assert len(json_files) == 0

    def test_meta_write_failure(self, device_config_dev, tmp_path, monkeypatch):
        """JSON sidecar write failure → PNG still saved."""
        from display.display_manager import DisplayManager

        dm = DisplayManager(device_config_dev)
        history_dir = str(tmp_path / "history_meta_fail")
        device_config_dev.history_image_dir = history_dir
        os.makedirs(history_dir, exist_ok=True)

        img = Image.new("RGB", (100, 100), "green")

        # Monkeypatch json.dump to fail
        import json as _json

        real_dump = _json.dump
        monkeypatch.setattr(
            _json, "dump", MagicMock(side_effect=TypeError("not serializable"))
        )

        dm._save_history_entry(img, history_meta={"plugin": "test"})

        # PNG should still exist
        png_files = [f for f in os.listdir(history_dir) if f.endswith(".png")]
        assert len(png_files) == 1


class TestDisplayImageHashSkip:
    def test_same_image_skips_second_display(self, device_config_dev, tmp_path):
        """Displaying same image twice → second call returns early."""
        from display.display_manager import DisplayManager

        dm = DisplayManager(device_config_dev)

        img = Image.new("RGB", (800, 480), "white")

        # First display
        result1 = dm.display_image(img)
        assert result1["preprocess_ms"] >= 0

        # Second display with same image → skip
        result2 = dm.display_image(img)
        assert result2["preprocess_ms"] == 0
        assert result2["display_ms"] == 0
