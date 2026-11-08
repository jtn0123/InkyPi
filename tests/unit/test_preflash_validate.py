"""Behavioural tests for ``scripts/preflash_validate.sh`` phase handling.

``run_phase`` used to call each suite as ``if "$@"; then``. Bash ignores
``set -e`` for every command run from an ``if`` condition, so a multi-command
suite reported only the status of its last command (CI showed the coverage
subset failing and the phase still printing ``PASS coverage ok``). These tests
source the script, which defines its helpers without running ``main``, and
drive ``run_phase`` directly.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "preflash_validate.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def _run(snippet: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    script = f'source "{SCRIPT}"\n{snippet}\n'
    return subprocess.run(
        ["bash", "-c", script],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _suite_names(cwd: Path) -> list[str]:
    result = _run("declare -F | awk '{print $3}'", cwd)
    assert result.returncode == 0, result.stderr
    return sorted(
        name for name in result.stdout.split() if name.endswith(("_suite", "_check"))
    )


def test_sourcing_does_not_run_validation(tmp_path: Path) -> None:
    result = _run("true", tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert "FAIL" not in result.stderr


def test_first_command_failure_fails_phase(tmp_path: Path) -> None:
    result = _run(
        "demo_suite() {\n"
        "    false\n"
        "    echo reached-after-failure\n"
        "    true\n"
        "}\n"
        "run_phase demo demo_suite",
        tmp_path,
    )
    assert result.returncode != 0
    assert "FAIL demo" in result.stderr
    assert "PASS demo" not in result.stdout
    assert "reached-after-failure" not in result.stdout


def test_middle_pipeline_failure_fails_phase(tmp_path: Path) -> None:
    result = _run(
        "demo_suite() {\n"
        "    false | cat\n"
        "    true\n"
        "}\n"
        "run_phase demo demo_suite",
        tmp_path,
    )
    assert result.returncode != 0
    assert "FAIL demo" in result.stderr


def test_passing_suite_reports_pass(tmp_path: Path) -> None:
    result = _run(
        "demo_suite() {\n    true\n    true\n}\nrun_phase demo demo_suite",
        tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert "PASS demo" in result.stdout


def test_phase_exports_do_not_leak(tmp_path: Path) -> None:
    result = _run(
        "demo_suite() {\n    export LEAKY_VALUE=1\n}\n"
        "run_phase demo demo_suite\n"
        'echo "after=${LEAKY_VALUE:-unset}"',
        tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert "after=unset" in result.stdout


def test_every_suite_stops_at_its_first_failure(tmp_path: Path) -> None:
    """Every real suite must fail when its first python command fails.

    ``python``/``python3`` are replaced with shell functions that fail on the
    first call and succeed afterwards. A suite that ignored the failure would
    keep going, call python again and report PASS.
    """
    suites = _suite_names(tmp_path)
    assert "coverage_suite" in suites and "flake_suite" in suites
    for suite in suites:
        calls = tmp_path / f"{suite}.calls"
        result = _run(
            "fake_python() {\n"
            f'    echo x >> "{calls}"\n'
            f'    [[ "$(wc -l < "{calls}")" -gt 1 ]]\n'
            "}\n"
            "python() { fake_python; }\n"
            "python3() { fake_python; }\n"
            "fc-list() { true; }\n"
            f"run_phase {suite} {suite}",
            tmp_path,
        )
        assert result.returncode != 0, f"{suite} passed despite a failing command"
        assert f"FAIL {suite}" in result.stderr
        call_count = len(calls.read_text().splitlines()) if calls.exists() else 0
        assert call_count <= 1, f"{suite} kept running after a failure"


def test_coverage_subset_does_not_apply_global_fail_under() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    body = text.split("coverage_suite() {", 1)[1].split("\n}\n", 1)[0]
    assert "--cov-fail-under=0" in body
    assert "scripts/coverage_gate.py" in body
