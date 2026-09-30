"""Installed versions and lock changes must fail before tests run."""

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def doctor() -> Any:
    path = Path(__file__).parents[2] / "scripts/dev_environment.py"
    spec = importlib.util.spec_from_file_location("dev_environment", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_drift_respects_markers_and_detects_changed_versions(
    doctor: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock = tmp_path / "requirements.txt"
    lock.write_text(
        'example==2.0 \\\n    --hash=sha256:abc\n# comment\nmissing==1.0\nwindows-only==1.0 ; sys_platform == "win32"\n'
    )

    def version(name: str) -> str:
        if name == "example":
            return "1.0"
        raise doctor.importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(doctor.importlib.metadata, "version", version)
    assert doctor.installed_drift(lock) == [
        "example: installed 1.0, expected ==2.0",
        "missing: missing",
    ]


def test_changed_or_corrupt_stamp_requires_sync(
    doctor: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(doctor, "installed_drift", list)
    stamp = tmp_path / "stamp.json"
    # CI can install the same hashed requirements directly without a stamp.
    assert doctor.check_environment(stamp, "current") == []
    stamp.write_text('{"fingerprint":"old"}')
    assert doctor.check_environment(stamp, "current")
    stamp.write_text("broken")
    assert doctor.check_environment(stamp, "current")
    stamp.write_text('{"fingerprint":"current"}')
    assert doctor.check_environment(stamp, "current") == []


def test_current_environment_passes_without_network_or_install() -> None:
    path = Path(__file__).parents[2] / "scripts/dev_environment.py"
    result = subprocess.run(
        [sys.executable, str(path)], capture_output=True, text=True, timeout=15
    )
    assert result.returncode == 0, result.stderr
    assert "matches committed" in result.stdout
