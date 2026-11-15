"""Installed versions and lock changes must fail before tests run."""

import importlib.util
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest
from packaging.specifiers import SpecifierSet


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


def test_supported_python_matches_pyproject_and_venv_script(doctor: Any) -> None:
    root = Path(__file__).parents[2]
    requires = tomllib.loads((root / "pyproject.toml").read_text())["project"][
        "requires-python"
    ]
    major, minor = doctor.SUPPORTED_PYTHON
    allowed = SpecifierSet(requires)
    assert allowed.contains(f"{major}.{minor}.0")
    assert not allowed.contains(f"{major}.{minor + 1}.0")
    assert not allowed.contains(f"{major}.{minor - 1}.0")
    venv_sh = (root / "scripts/venv.sh").read_text()
    assert f'INKYPI_PYTHON_VERSION="{major}.{minor}"' in venv_sh


def test_interpreter_problem_names_both_versions(doctor: Any) -> None:
    assert doctor.interpreter_problem(doctor.SUPPORTED_PYTHON) == ""
    major, minor = doctor.SUPPORTED_PYTHON
    problem = doctor.interpreter_problem((major, minor + 2))
    assert f"needs Python {major}.{minor}" in problem
    assert f"is Python {major}.{minor + 2}" in problem
    assert "rm -rf .venv" in problem


def test_sync_refuses_another_python_before_installing(
    doctor: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def no_install(*args: object, **kwargs: object) -> None:
        raise AssertionError("sync must not install into the wrong Python")

    monkeypatch.setattr(doctor.subprocess, "run", no_install)
    monkeypatch.setattr(doctor, "interpreter_problem", lambda: "wrong python")
    monkeypatch.setattr(doctor.sys, "argv", ["dev_environment.py", "--sync"])
    monkeypatch.setattr(doctor.sys, "base_prefix", "/usr")
    monkeypatch.setattr(doctor.sys, "prefix", "/project/.venv")

    assert doctor.main() == 1
    assert "wrong python" in capsys.readouterr().err
