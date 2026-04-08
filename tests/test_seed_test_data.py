"""Tests for scripts/seed_test_data.py."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helper: load the script without polluting sys.path
# ---------------------------------------------------------------------------


def _load_script():
    scripts_dir = Path(__file__).parent.parent / "scripts"
    spec = importlib.util.spec_from_file_location(
        "seed_test_data", scripts_dir / "seed_test_data.py"
    )
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


@pytest.fixture(scope="module")
def seed_mod():
    return _load_script()


# ---------------------------------------------------------------------------
# Helpers used across tests
# ---------------------------------------------------------------------------


def _make_mock_device_json(directory: Path) -> None:
    """Write a minimal mock-display device.json into *directory*."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "device.json").write_text(
        json.dumps({"display_type": "mock", "name": "Test"}), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Basic seeding: expected files are created
# ---------------------------------------------------------------------------


class TestBasicSeed:
    def test_creates_history_pngs(self, seed_mod, tmp_path):
        seed_mod.run(["--target-dir", str(tmp_path), "--count", "5"])
        history_dir = tmp_path / "history"
        pngs = list(history_dir.glob("display_*.png"))
        assert len(pngs) == 5

    def test_creates_history_sidecars(self, seed_mod, tmp_path):
        seed_mod.run(["--target-dir", str(tmp_path), "--count", "5"])
        history_dir = tmp_path / "history"
        jsons = list(history_dir.glob("display_*.json"))
        assert len(jsons) == 5

    def test_creates_device_json(self, seed_mod, tmp_path):
        seed_mod.run(["--target-dir", str(tmp_path), "--count", "3"])
        device_json = tmp_path / "device.json"
        assert device_json.exists()

    def test_device_json_has_playlist(self, seed_mod, tmp_path):
        seed_mod.run(["--target-dir", str(tmp_path), "--count", "3"])
        data = json.loads((tmp_path / "device.json").read_text())
        playlists = data["playlist_config"]["playlists"]
        assert len(playlists) >= 1
        assert playlists[0]["name"] == "Seed Playlist"

    def test_device_json_has_plugins(self, seed_mod, tmp_path):
        seed_mod.run(["--target-dir", str(tmp_path), "--count", "3"])
        data = json.loads((tmp_path / "device.json").read_text())
        plugins = data["playlist_config"]["playlists"][0]["plugins"]
        plugin_ids = {p["plugin_id"] for p in plugins}
        assert "year_progress" in plugin_ids
        assert "weather" in plugin_ids
        assert "calendar" in plugin_ids

    def test_no_real_api_keys(self, seed_mod, tmp_path):
        seed_mod.run(["--target-dir", str(tmp_path), "--count", "3"])
        raw = (tmp_path / "device.json").read_text()
        # Any real-looking credential would be a long alphanumeric string;
        # the placeholder must be clearly labelled.
        assert "PLACEHOLDER" in raw

    def test_default_count_is_20(self, seed_mod, tmp_path):
        seed_mod.run(["--target-dir", str(tmp_path)])
        history_dir = tmp_path / "history"
        pngs = list(history_dir.glob("display_*.png"))
        assert len(pngs) == 20


# ---------------------------------------------------------------------------
# Sidecar JSON validity
# ---------------------------------------------------------------------------


class TestSidecarJson:
    def test_sidecar_is_valid_json(self, seed_mod, tmp_path):
        seed_mod.run(["--target-dir", str(tmp_path), "--count", "5"])
        history_dir = tmp_path / "history"
        for sidecar in history_dir.glob("display_*.json"):
            data = json.loads(sidecar.read_text())
            assert isinstance(data, dict)

    def test_sidecar_has_required_fields(self, seed_mod, tmp_path):
        seed_mod.run(["--target-dir", str(tmp_path), "--count", "5"])
        history_dir = tmp_path / "history"
        for sidecar in history_dir.glob("display_*.json"):
            data = json.loads(sidecar.read_text())
            assert "plugin_id" in data
            assert "status" in data
            assert "timestamp" in data

    def test_sidecar_status_values(self, seed_mod, tmp_path):
        seed_mod.run(["--target-dir", str(tmp_path), "--count", "8"])
        history_dir = tmp_path / "history"
        statuses = set()
        for sidecar in history_dir.glob("display_*.json"):
            data = json.loads(sidecar.read_text())
            assert data["status"] in ("success", "failure")
            statuses.add(data["status"])
        # With 8 entries we expect both success and failure to appear
        assert "success" in statuses
        assert "failure" in statuses

    def test_png_and_sidecar_stems_match(self, seed_mod, tmp_path):
        seed_mod.run(["--target-dir", str(tmp_path), "--count", "5"])
        history_dir = tmp_path / "history"
        png_stems = {p.stem for p in history_dir.glob("display_*.png")}
        json_stems = {j.stem for j in history_dir.glob("display_*.json")}
        assert png_stems == json_stems


# ---------------------------------------------------------------------------
# Safety: refuse src/config target
# ---------------------------------------------------------------------------


class TestSafety:
    def test_refuses_src_config(self, seed_mod):
        src_config = str(Path(__file__).parent.parent / "src" / "config")
        with pytest.raises(SystemExit) as exc_info:
            seed_mod.run(["--target-dir", src_config, "--count", "1"])
        assert exc_info.value.code != 0

    def test_refuses_nested_under_src_config(self, seed_mod):
        nested = str(Path(__file__).parent.parent / "src" / "config" / "subdir")
        with pytest.raises(SystemExit) as exc_info:
            seed_mod.run(["--target-dir", nested, "--count", "1"])
        assert exc_info.value.code != 0

    def test_refuses_non_mock_device_json(self, seed_mod, tmp_path):
        (tmp_path / "device.json").write_text(
            json.dumps({"display_type": "inky", "name": "Prod"}), encoding="utf-8"
        )
        with pytest.raises(SystemExit) as exc_info:
            seed_mod.run(["--target-dir", str(tmp_path), "--count", "1"])
        assert exc_info.value.code != 0

    def test_refuses_dev_false(self, seed_mod, tmp_path):
        (tmp_path / "device.json").write_text(
            json.dumps({"display_type": "mock", "dev": False}), encoding="utf-8"
        )
        with pytest.raises(SystemExit) as exc_info:
            seed_mod.run(["--target-dir", str(tmp_path), "--count", "1"])
        assert exc_info.value.code != 0

    def test_allows_empty_target_dir(self, seed_mod, tmp_path):
        # No device.json at all — should be safe
        seed_mod.run(["--target-dir", str(tmp_path), "--count", "2"])
        assert (tmp_path / "history").exists()

    def test_allows_mock_device_json(self, seed_mod, tmp_path):
        _make_mock_device_json(tmp_path)
        seed_mod.run(["--target-dir", str(tmp_path), "--count", "2"])
        assert (tmp_path / "history").exists()


# ---------------------------------------------------------------------------
# Idempotency: second run is a no-op
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_second_run_no_extra_pngs(self, seed_mod, tmp_path):
        seed_mod.run(["--target-dir", str(tmp_path), "--count", "5"])
        seed_mod.run(["--target-dir", str(tmp_path), "--count", "5"])
        history_dir = tmp_path / "history"
        pngs = list(history_dir.glob("display_*.png"))
        assert len(pngs) == 5

    def test_second_run_no_extra_playlists(self, seed_mod, tmp_path):
        seed_mod.run(["--target-dir", str(tmp_path), "--count", "3"])
        seed_mod.run(["--target-dir", str(tmp_path), "--count", "3"])
        data = json.loads((tmp_path / "device.json").read_text())
        playlists = data["playlist_config"]["playlists"]
        seed_playlists = [p for p in playlists if p["name"] == "Seed Playlist"]
        assert len(seed_playlists) == 1


# ---------------------------------------------------------------------------
# --reset: wipes and reseeds
# ---------------------------------------------------------------------------


class TestReset:
    def test_reset_wipes_history(self, seed_mod, tmp_path):
        seed_mod.run(["--target-dir", str(tmp_path), "--count", "5"])
        # Add a stray file that --reset should remove
        (tmp_path / "history" / "stray_file.png").write_bytes(b"")
        seed_mod.run(["--target-dir", str(tmp_path), "--count", "3", "--reset"])
        history_dir = tmp_path / "history"
        pngs = list(history_dir.glob("display_*.png"))
        assert len(pngs) == 3
        assert not (history_dir / "stray_file.png").exists()

    def test_reset_reseeds_different_count(self, seed_mod, tmp_path):
        seed_mod.run(["--target-dir", str(tmp_path), "--count", "10"])
        seed_mod.run(["--target-dir", str(tmp_path), "--count", "4", "--reset"])
        history_dir = tmp_path / "history"
        pngs = list(history_dir.glob("display_*.png"))
        assert len(pngs) == 4

    def test_reset_reseeds_playlist(self, seed_mod, tmp_path):
        seed_mod.run(["--target-dir", str(tmp_path), "--count", "3"])
        seed_mod.run(["--target-dir", str(tmp_path), "--count", "3", "--reset"])
        data = json.loads((tmp_path / "device.json").read_text())
        playlists = data["playlist_config"]["playlists"]
        seed_playlists = [p for p in playlists if p["name"] == "Seed Playlist"]
        assert len(seed_playlists) == 1
