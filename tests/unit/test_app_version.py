"""One version reader, used by startup, /api/version/info and diagnostics.

There were three copies. The diagnostics copy didn't reject the bootstrap
"0.1.0" placeholder and had no pyproject fallback, so it could report a
different version from the rest of the UI.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from utils.app_version import read_app_version


def _repo(tmp_path: Path, version: str | None, pyproject: str | None) -> Path:
    if version is not None:
        (tmp_path / "VERSION").write_text(version)
    if pyproject is not None:
        (tmp_path / "pyproject.toml").write_text(pyproject)
    return tmp_path


PYPROJECT = '[project]\nname = "inkypi"\nversion = "7.7.7"\n'


def test_reads_and_strips_version(tmp_path: Path) -> None:
    assert read_app_version(_repo(tmp_path, "1.2.3\n", PYPROJECT)) == "1.2.3"


@pytest.mark.parametrize(
    "version",
    [None, "", "\n", "{version}\n", "0.1.0\n"],
    ids=["missing", "empty", "blank", "template", "bootstrap"],
)
def test_falls_back_to_pyproject(tmp_path: Path, version: str | None) -> None:
    assert read_app_version(_repo(tmp_path, version, PYPROJECT)) == "7.7.7"


@pytest.mark.parametrize(
    "pyproject",
    [None, "not = [valid toml", '[project]\nname = "inkypi"\n'],
    ids=["missing", "malformed", "no-version"],
)
def test_unknown_when_neither_source_has_a_version(
    tmp_path: Path, pyproject: str | None
) -> None:
    assert read_app_version(_repo(tmp_path, "{version}", pyproject)) == "unknown"


def test_the_repo_resolves_to_a_real_version() -> None:
    version = read_app_version()
    assert version not in {"", "unknown", "{version}", "0.1.0"}


def test_version_info_reports_the_shared_version() -> None:
    import blueprints.version_info as version_info

    assert read_app_version() == version_info._APP_VERSION
