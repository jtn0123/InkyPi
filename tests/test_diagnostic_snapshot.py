"""Tests for scripts/diagnostic_snapshot.py."""

from __future__ import annotations

import importlib.util
import json
import tarfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helper: load script without importing from src/
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
def diag_mod():
    return _load_script("diagnostic_snapshot")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_config_dir(base: Path, extra_keys: dict | None = None) -> Path:
    """Create a minimal config dir with device.json."""
    config_dir = base / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    device: dict = {
        "name": "TestDevice",
        "display_type": "mock",
        "resolution": [800, 480],
        "timezone": "UTC",
        "api_key": "super-secret-api-key-12345",
        "weather_token": "hidden-weather-token",
        "admin_password": "hunter2",
        "secret_pin": "1234",
        "safe_setting": "keep-this-value",
        "another_safe": 42,
    }
    if extra_keys:
        device.update(extra_keys)
    (config_dir / "device.json").write_text(json.dumps(device))
    return config_dir


def _make_log_file(base: Path, lines: int = 20) -> Path:
    log_file = base / "inkypi.log"
    content = "\n".join(f"2026-01-01T00:00:00 INFO line {i}" for i in range(lines))
    log_file.write_text(content + "\n")
    return log_file


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDiagnosticSnapshot:
    def test_tarball_is_created(self, diag_mod, tmp_path):
        """run_snapshot creates a valid .tar.gz file."""
        config_dir = _make_config_dir(tmp_path)
        output = str(tmp_path / "diag.tar.gz")

        rc = diag_mod.run_snapshot(
            output=output,
            config_dir=str(config_dir),
            log_path=None,
            log_lines=500,
        )

        assert rc == 0
        assert (tmp_path / "diag.tar.gz").is_file()
        assert tarfile.is_tarfile(output)

    def test_manifest_present_and_valid(self, diag_mod, tmp_path):
        """Tarball contains manifest.json with required fields."""
        config_dir = _make_config_dir(tmp_path)
        output = str(tmp_path / "diag.tar.gz")

        diag_mod.run_snapshot(
            output=output,
            config_dir=str(config_dir),
            log_path=None,
            log_lines=500,
        )

        with tarfile.open(output, "r:gz") as tar:
            member = tar.getmember("manifest.json")
            manifest = json.loads(tar.extractfile(member).read())

        assert manifest["snapshot_version"] == diag_mod.SNAPSHOT_FORMAT_VERSION
        assert "timestamp" in manifest
        assert "files" in manifest
        assert isinstance(manifest["files"], list)
        assert len(manifest["files"]) >= 1

    def test_system_info_present(self, diag_mod, tmp_path):
        """Tarball contains system_info.txt."""
        config_dir = _make_config_dir(tmp_path)
        output = str(tmp_path / "diag.tar.gz")

        diag_mod.run_snapshot(
            output=output,
            config_dir=str(config_dir),
            log_path=None,
            log_lines=500,
        )

        with tarfile.open(output, "r:gz") as tar:
            names = tar.getnames()

        assert "system_info.txt" in names

    def test_system_info_has_expected_sections(self, diag_mod, tmp_path):
        """system_info.txt mentions uname, disk, python sections."""
        config_dir = _make_config_dir(tmp_path)
        output = str(tmp_path / "diag.tar.gz")

        diag_mod.run_snapshot(
            output=output,
            config_dir=str(config_dir),
            log_path=None,
            log_lines=500,
        )

        with tarfile.open(output, "r:gz") as tar:
            text = tar.extractfile("system_info.txt").read().decode("utf-8")

        assert "uname" in text.lower() or "system" in text.lower()
        assert "python" in text.lower()

    def test_redacted_config_present(self, diag_mod, tmp_path):
        """Tarball contains config_redacted.json."""
        config_dir = _make_config_dir(tmp_path)
        output = str(tmp_path / "diag.tar.gz")

        diag_mod.run_snapshot(
            output=output,
            config_dir=str(config_dir),
            log_path=None,
            log_lines=500,
        )

        with tarfile.open(output, "r:gz") as tar:
            names = tar.getnames()

        assert "config_redacted.json" in names

    def test_api_key_is_redacted(self, diag_mod, tmp_path):
        """config_redacted.json must NOT contain the raw api_key value."""
        config_dir = _make_config_dir(tmp_path)
        output = str(tmp_path / "diag.tar.gz")

        diag_mod.run_snapshot(
            output=output,
            config_dir=str(config_dir),
            log_path=None,
            log_lines=500,
        )

        with tarfile.open(output, "r:gz") as tar:
            redacted = json.loads(tar.extractfile("config_redacted.json").read())

        assert redacted.get("api_key") == "***REDACTED***"
        # Literal secret value must not appear anywhere in the JSON
        raw_json = json.dumps(redacted)
        assert "super-secret-api-key-12345" not in raw_json

    def test_token_is_redacted(self, diag_mod, tmp_path):
        """Keys containing 'token' are redacted."""
        config_dir = _make_config_dir(tmp_path)
        output = str(tmp_path / "diag.tar.gz")

        diag_mod.run_snapshot(
            output=output,
            config_dir=str(config_dir),
            log_path=None,
            log_lines=500,
        )

        with tarfile.open(output, "r:gz") as tar:
            redacted = json.loads(tar.extractfile("config_redacted.json").read())

        assert redacted.get("weather_token") == "***REDACTED***"
        raw_json = json.dumps(redacted)
        assert "hidden-weather-token" not in raw_json

    def test_password_is_redacted(self, diag_mod, tmp_path):
        """Keys containing 'password' are redacted."""
        config_dir = _make_config_dir(tmp_path)
        output = str(tmp_path / "diag.tar.gz")

        diag_mod.run_snapshot(
            output=output,
            config_dir=str(config_dir),
            log_path=None,
            log_lines=500,
        )

        with tarfile.open(output, "r:gz") as tar:
            redacted = json.loads(tar.extractfile("config_redacted.json").read())

        assert redacted.get("admin_password") == "***REDACTED***"
        raw_json = json.dumps(redacted)
        assert "hunter2" not in raw_json

    def test_pin_is_redacted(self, diag_mod, tmp_path):
        """Keys containing 'pin' are redacted."""
        config_dir = _make_config_dir(tmp_path)
        output = str(tmp_path / "diag.tar.gz")

        diag_mod.run_snapshot(
            output=output,
            config_dir=str(config_dir),
            log_path=None,
            log_lines=500,
        )

        with tarfile.open(output, "r:gz") as tar:
            redacted = json.loads(tar.extractfile("config_redacted.json").read())

        assert redacted.get("secret_pin") == "***REDACTED***"

    def test_non_secret_keys_preserved(self, diag_mod, tmp_path):
        """Non-secret keys like 'name' and 'safe_setting' must survive redaction."""
        config_dir = _make_config_dir(tmp_path)
        output = str(tmp_path / "diag.tar.gz")

        diag_mod.run_snapshot(
            output=output,
            config_dir=str(config_dir),
            log_path=None,
            log_lines=500,
        )

        with tarfile.open(output, "r:gz") as tar:
            redacted = json.loads(tar.extractfile("config_redacted.json").read())

        assert redacted.get("name") == "TestDevice"
        assert redacted.get("safe_setting") == "keep-this-value"
        assert redacted.get("another_safe") == 42
        assert redacted.get("timezone") == "UTC"

    def test_log_included_when_file_exists(self, diag_mod, tmp_path):
        """recent_logs.txt is included when log_path points to an existing file."""
        config_dir = _make_config_dir(tmp_path)
        log_file = _make_log_file(tmp_path, lines=30)
        output = str(tmp_path / "diag.tar.gz")

        diag_mod.run_snapshot(
            output=output,
            config_dir=str(config_dir),
            log_path=str(log_file),
            log_lines=10,
        )

        with tarfile.open(output, "r:gz") as tar:
            names = tar.getnames()
            assert "recent_logs.txt" in names
            text = tar.extractfile("recent_logs.txt").read().decode("utf-8")

        # Only last 10 lines of 30 should be present (lines 20-29)
        assert "line 29" in text
        assert "line 20" in text
        # Lines before the tail window should not appear
        assert "line 0" not in text
        assert "line 19" not in text

    def test_missing_log_file_handled_gracefully(self, diag_mod, tmp_path):
        """run_snapshot succeeds even when the log file does not exist."""
        config_dir = _make_config_dir(tmp_path)
        output = str(tmp_path / "diag.tar.gz")

        rc = diag_mod.run_snapshot(
            output=output,
            config_dir=str(config_dir),
            log_path=str(tmp_path / "nonexistent.log"),
            log_lines=500,
        )

        assert rc == 0
        assert tarfile.is_tarfile(output)

        with tarfile.open(output, "r:gz") as tar:
            names = tar.getnames()
        # recent_logs.txt should be absent, not an error entry
        assert "recent_logs.txt" not in names

    def test_missing_log_omitted_from_manifest(self, diag_mod, tmp_path):
        """When log is missing, manifest.files should not list recent_logs.txt."""
        config_dir = _make_config_dir(tmp_path)
        output = str(tmp_path / "diag.tar.gz")

        diag_mod.run_snapshot(
            output=output,
            config_dir=str(config_dir),
            log_path=None,
            log_lines=500,
        )

        with tarfile.open(output, "r:gz") as tar:
            manifest = json.loads(tar.extractfile("manifest.json").read())

        assert "recent_logs.txt" not in manifest["files"]

    def test_missing_device_json_handled_gracefully(self, diag_mod, tmp_path):
        """run_snapshot does not crash when device.json is absent."""
        empty_config = tmp_path / "empty_config"
        empty_config.mkdir()
        output = str(tmp_path / "diag.tar.gz")

        rc = diag_mod.run_snapshot(
            output=output,
            config_dir=str(empty_config),
            log_path=None,
            log_lines=500,
        )

        assert rc == 0
        assert tarfile.is_tarfile(output)

    def test_redact_dict_nested(self, diag_mod):
        """_redact_dict handles nested structures recursively."""
        data = {
            "outer": "visible",
            "nested": {
                "api_key": "nested-secret",
                "safe": "still-visible",
            },
            "list_field": [
                {"token": "list-secret"},
                {"plain": "list-plain"},
            ],
        }
        result = diag_mod._redact_dict(data)
        assert result["outer"] == "visible"
        assert result["nested"]["api_key"] == "***REDACTED***"
        assert result["nested"]["safe"] == "still-visible"
        assert result["list_field"][0]["token"] == "***REDACTED***"
        assert result["list_field"][1]["plain"] == "list-plain"

    def test_default_output_path_format(self, diag_mod):
        """_default_output_path returns an inkypi-diag-*.tar.gz string."""
        path = diag_mod._default_output_path()
        assert path.startswith("inkypi-diag-")
        assert path.endswith(".tar.gz")

    def test_is_secret_key_detection(self, diag_mod):
        """_is_secret_key correctly identifies secret-like key names."""
        assert diag_mod._is_secret_key("api_key") is True
        assert diag_mod._is_secret_key("weather_token") is True
        assert diag_mod._is_secret_key("admin_password") is True
        assert diag_mod._is_secret_key("SECRET") is True
        assert diag_mod._is_secret_key("secret_pin") is True
        assert diag_mod._is_secret_key("MY_API_KEY") is True
        # Non-secret keys
        assert diag_mod._is_secret_key("name") is False
        assert diag_mod._is_secret_key("display_type") is False
        assert diag_mod._is_secret_key("resolution") is False
        assert diag_mod._is_secret_key("timezone") is False
