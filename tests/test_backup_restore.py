"""Tests for scripts/backup_config.py and scripts/restore_config.py."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import tarfile
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Helpers to load scripts without importing from src/
# ---------------------------------------------------------------------------


def _load_script(script_name: str):
    """Load a scripts/ module by file path, avoiding sys.path pollution."""
    scripts_dir = Path(__file__).parent.parent / "scripts"
    spec = importlib.util.spec_from_file_location(
        script_name, scripts_dir / f"{script_name}.py"
    )
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


@pytest.fixture(scope="module")
def backup_mod():
    return _load_script("backup_config")


@pytest.fixture(scope="module")
def restore_mod():
    return _load_script("restore_config")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_config_dir(base: Path) -> Path:
    config_dir = base / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    device = {
        "name": "TestDevice",
        "display_type": "mock",
        "resolution": [800, 480],
        "orientation": "horizontal",
        "plugin_order": [],
        "playlist_config": {"playlists": [], "active_playlist": None},
        "refresh_info": {
            "refresh_time": None,
            "image_hash": None,
            "refresh_type": None,
            "plugin_id": None,
        },
    }
    (config_dir / "device.json").write_text(json.dumps(device))
    (config_dir / "extra.json").write_text(json.dumps({"foo": "bar"}))
    return config_dir


def _make_instances_dir(base: Path) -> Path:
    inst_dir = base / "instances"
    inst_dir.mkdir(parents=True, exist_ok=True)
    plugin_dir = inst_dir / "weather"
    plugin_dir.mkdir()
    (plugin_dir / "weather_default.png").write_bytes(b"\x89PNG\r\n")
    return inst_dir


# ---------------------------------------------------------------------------
# backup_config tests
# ---------------------------------------------------------------------------


class TestBackupConfig:
    def test_backup_creates_valid_tar_gz(self, backup_mod, tmp_path):
        config_dir = _make_config_dir(tmp_path / "src")
        instances_dir = _make_instances_dir(tmp_path / "src")
        output = str(tmp_path / "backup.tar.gz")

        rc = backup_mod.run_backup(
            output=output,
            config_dir=str(config_dir),
            instances_dir=str(instances_dir),
            include_history=False,
        )

        assert rc == 0
        assert os.path.isfile(output)
        assert tarfile.is_tarfile(output)

    def test_manifest_contains_expected_fields(self, backup_mod, tmp_path):
        config_dir = _make_config_dir(tmp_path / "src")
        instances_dir = _make_instances_dir(tmp_path / "src")
        output = str(tmp_path / "backup.tar.gz")

        backup_mod.run_backup(
            output=output,
            config_dir=str(config_dir),
            instances_dir=str(instances_dir),
            include_history=False,
        )

        with tarfile.open(output, "r:gz") as tar:
            member = tar.getmember("manifest.json")
            fobj = tar.extractfile(member)
            manifest = json.loads(fobj.read().decode("utf-8"))

        assert manifest["backup_version"] == backup_mod.BACKUP_FORMAT_VERSION
        assert "timestamp" in manifest
        assert "included_paths" in manifest
        assert "device_json_checksum" in manifest
        assert manifest["device_json_checksum"] is not None
        # All included paths should be strings
        assert all(isinstance(p, str) for p in manifest["included_paths"])

    def test_backup_includes_config_and_instance_files(self, backup_mod, tmp_path):
        config_dir = _make_config_dir(tmp_path / "src")
        instances_dir = _make_instances_dir(tmp_path / "src")
        output = str(tmp_path / "backup.tar.gz")

        backup_mod.run_backup(
            output=output,
            config_dir=str(config_dir),
            instances_dir=str(instances_dir),
            include_history=False,
        )

        with tarfile.open(output, "r:gz") as tar:
            names = tar.getnames()

        assert "manifest.json" in names
        assert any(n.startswith("config/") and n.endswith(".json") for n in names)

    def test_backup_excludes_history_by_default(self, backup_mod, tmp_path):
        config_dir = _make_config_dir(tmp_path / "src")
        instances_dir = _make_instances_dir(tmp_path / "src")
        history_dir = tmp_path / "src" / "history"
        history_dir.mkdir()
        (history_dir / "img_001.png").write_bytes(b"\x89PNG")

        output = str(tmp_path / "backup.tar.gz")
        backup_mod.run_backup(
            output=output,
            config_dir=str(config_dir),
            instances_dir=str(instances_dir),
            include_history=False,
            history_dir=str(history_dir),
        )

        with tarfile.open(output, "r:gz") as tar:
            names = tar.getnames()

        assert not any(n.startswith("history/") for n in names)

    def test_backup_includes_history_when_flag_set(self, backup_mod, tmp_path):
        config_dir = _make_config_dir(tmp_path / "src")
        instances_dir = _make_instances_dir(tmp_path / "src")
        history_dir = tmp_path / "src" / "history"
        history_dir.mkdir()
        (history_dir / "img_001.png").write_bytes(b"\x89PNG")

        output = str(tmp_path / "backup.tar.gz")
        backup_mod.run_backup(
            output=output,
            config_dir=str(config_dir),
            instances_dir=str(instances_dir),
            include_history=True,
            history_dir=str(history_dir),
        )

        with tarfile.open(output, "r:gz") as tar:
            names = tar.getnames()

        assert any(n.startswith("history/") for n in names)

    def test_manifest_checksum_matches_device_json(self, backup_mod, tmp_path):
        config_dir = _make_config_dir(tmp_path / "src")
        instances_dir = _make_instances_dir(tmp_path / "src")
        output = str(tmp_path / "backup.tar.gz")

        backup_mod.run_backup(
            output=output,
            config_dir=str(config_dir),
            instances_dir=str(instances_dir),
            include_history=False,
        )

        device_json_path = config_dir / "device.json"
        h = hashlib.sha256(device_json_path.read_bytes()).hexdigest()

        with tarfile.open(output, "r:gz") as tar:
            fobj = tar.extractfile("manifest.json")
            manifest = json.loads(fobj.read())

        assert manifest["device_json_checksum"] == h


# ---------------------------------------------------------------------------
# restore_config tests
# ---------------------------------------------------------------------------


class TestRestoreConfig:
    def _make_backup(self, backup_mod, src_base: Path, output: str) -> str:
        config_dir = _make_config_dir(src_base)
        instances_dir = _make_instances_dir(src_base)
        backup_mod.run_backup(
            output=output,
            config_dir=str(config_dir),
            instances_dir=str(instances_dir),
            include_history=False,
        )
        return output

    def test_restore_round_trip(self, backup_mod, restore_mod, tmp_path):
        """backup → wipe → restore → contents match original."""
        src = tmp_path / "original"
        src.mkdir()
        config_dir = _make_config_dir(src)
        instances_dir = _make_instances_dir(src)
        original_device = (config_dir / "device.json").read_text()

        backup_path = str(tmp_path / "backup.tar.gz")
        backup_mod.run_backup(
            output=backup_path,
            config_dir=str(config_dir),
            instances_dir=str(instances_dir),
            include_history=False,
        )

        # Wipe current state
        (config_dir / "device.json").unlink()

        # Restore
        rc = restore_mod.run_restore(
            backup_path=backup_path,
            config_dir=str(config_dir),
            instances_dir=str(instances_dir),
            yes=True,
        )

        assert rc == 0
        restored = (config_dir / "device.json").read_text()
        assert json.loads(restored) == json.loads(original_device)

    def test_restore_without_yes_shows_prompt(self, backup_mod, restore_mod, tmp_path):
        """restore without --yes should call the input function for confirmation."""
        src = tmp_path / "src"
        src.mkdir()
        config_dir = _make_config_dir(src)
        instances_dir = _make_instances_dir(src)

        backup_path = str(tmp_path / "backup.tar.gz")
        backup_mod.run_backup(
            output=backup_path,
            config_dir=str(config_dir),
            instances_dir=str(instances_dir),
            include_history=False,
        )

        prompts: list[str] = []

        def mock_input(prompt: str) -> str:
            prompts.append(prompt)
            return "n"  # decline

        rc = restore_mod.run_restore(
            backup_path=backup_path,
            config_dir=str(config_dir),
            instances_dir=str(instances_dir),
            yes=False,
            _input_fn=mock_input,
        )

        assert len(prompts) == 1
        assert rc == 1  # user declined

    def test_restore_creates_pre_restore_safety_backup(
        self, backup_mod, restore_mod, tmp_path, monkeypatch
    ):
        """restore --yes should create a .pre-restore-*.tar.gz next to the config."""
        src = tmp_path / "src"
        src.mkdir()
        config_dir = _make_config_dir(src)
        instances_dir = _make_instances_dir(src)

        backup_path = str(tmp_path / "backup.tar.gz")
        backup_mod.run_backup(
            output=backup_path,
            config_dir=str(config_dir),
            instances_dir=str(instances_dir),
            include_history=False,
        )

        safety_outputs: list[str] = []
        original_pre_restore = restore_mod._pre_restore_backup

        # JTN-538: pin the safety backup output dir to tmp_path so the
        # .pre-restore-*.tar.gz never leaks into the repo working tree.
        def capture_pre_restore(config_dir, instances_dir, output_dir=None):
            result = original_pre_restore(
                config_dir, instances_dir, output_dir=str(tmp_path)
            )
            safety_outputs.append(result)
            return result

        monkeypatch.setattr(restore_mod, "_pre_restore_backup", capture_pre_restore)

        restore_mod.run_restore(
            backup_path=backup_path,
            config_dir=str(config_dir),
            instances_dir=str(instances_dir),
            yes=True,
        )

        assert len(safety_outputs) == 1
        assert ".pre-restore-" in safety_outputs[0]
        assert os.path.isfile(safety_outputs[0])

    def test_restore_fails_on_missing_backup(self, restore_mod, tmp_path):
        """restore should return non-zero when backup file doesn't exist."""
        rc = restore_mod.run_restore(
            backup_path=str(tmp_path / "nonexistent.tar.gz"),
            config_dir=str(tmp_path / "config"),
            instances_dir=str(tmp_path / "instances"),
            yes=True,
        )
        assert rc != 0

    def test_restore_verifies_checksum(self, backup_mod, restore_mod, tmp_path):
        """After restore, device.json checksum should match the manifest."""
        src = tmp_path / "src"
        src.mkdir()
        config_dir = _make_config_dir(src)
        instances_dir = _make_instances_dir(src)

        backup_path = str(tmp_path / "backup.tar.gz")
        backup_mod.run_backup(
            output=backup_path,
            config_dir=str(config_dir),
            instances_dir=str(instances_dir),
            include_history=False,
        )

        rc = restore_mod.run_restore(
            backup_path=backup_path,
            config_dir=str(config_dir),
            instances_dir=str(instances_dir),
            yes=True,
        )

        assert rc == 0

    def test_restore_detects_tampered_device_json(
        self, backup_mod, restore_mod, tmp_path
    ):
        """If device.json is tampered after extraction, checksum mismatch should fail."""
        src = tmp_path / "src"
        src.mkdir()
        config_dir = _make_config_dir(src)
        instances_dir = _make_instances_dir(src)

        backup_path = str(tmp_path / "backup.tar.gz")
        backup_mod.run_backup(
            output=backup_path,
            config_dir=str(config_dir),
            instances_dir=str(instances_dir),
            include_history=False,
        )

        # Tamper with device.json after extraction by patching _sha256_file
        with patch.object(restore_mod, "_sha256_file", return_value="deadbeef"):
            rc = restore_mod.run_restore(
                backup_path=backup_path,
                config_dir=str(config_dir),
                instances_dir=str(instances_dir),
                yes=True,
            )

        assert rc != 0
