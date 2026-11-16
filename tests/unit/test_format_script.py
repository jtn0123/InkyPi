"""scripts/format.sh fails when Ruff or Black fails.

It used to capture `$?` inside `if ! tool; then`, where `$?` is the status of
the `!` (always 0), so it printed success and exited 0 after a failure. Each
case runs a copy of the script with fake ``ruff`` and ``black`` on PATH that
exit with a chosen status, so nothing is formatted.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

FORMAT_SH = Path(__file__).resolve().parents[2] / "scripts" / "format.sh"


def _fake_tool(path: Path, exit_code: int) -> None:
    path.write_text(f'#!/bin/sh\necho "{path.name} $*"\nexit {exit_code}\n')
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _run(tmp_path: Path, *, ruff: int, black: int) -> subprocess.CompletedProcess[str]:
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(FORMAT_SH, repo / "scripts" / "format.sh")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_tool(bin_dir / "ruff", ruff)
    _fake_tool(bin_dir / "black", black)
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "HOME": str(tmp_path),
        # An active venv: format.sh uses the tools on PATH instead of
        # sourcing scripts/venv.sh.
        "VIRTUAL_ENV": str(tmp_path / "venv"),
    }
    return subprocess.run(
        ["bash", str(repo / "scripts" / "format.sh")],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


@pytest.mark.parametrize(
    ("ruff", "black", "failed"),
    [(1, 0, "Ruff: 1"), (0, 123, "Black: 123"), (2, 1, "Ruff: 2")],
)
def test_a_failing_tool_fails_the_script(
    tmp_path: Path, ruff: int, black: int, failed: str
) -> None:
    result = _run(tmp_path, ruff=ruff, black=black)

    assert result.returncode == 1, result.stdout
    assert failed in result.stdout
    assert "All formatting completed successfully" not in result.stdout


def test_both_tools_passing_succeeds(tmp_path: Path) -> None:
    result = _run(tmp_path, ruff=0, black=0)

    assert result.returncode == 0, result.stdout
    assert "ruff check --fix src tests scripts" in result.stdout
    assert "black src tests scripts" in result.stdout
    assert "All formatting completed successfully" in result.stdout
