"""The retry budget reports retried tests and fails runs with too many.

Each case runs a real pytest session in a disposable project with
pytest-rerunfailures (and xdist for one case), using the repository's plugin.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_PLUGIN = Path(__file__).parents[1] / "helpers" / "rerun_budget.py"

_FLAKY_TEST = """
import pytest
from pathlib import Path

@pytest.mark.flaky(reruns=1)
def test_flaky_{n}(tmp_path_factory):
    marker = Path(__file__).parent / ".attempted_{n}"
    if not marker.exists():
        marker.write_text("1")
        raise AssertionError("first attempt of {n} failed")
"""


def _run(
    tmp_path: Path, flaky: int, *extra: str, budget: str | None = None
) -> tuple[int, str, str]:
    shutil.copy(_PLUGIN, tmp_path / "rerun_budget.py")
    (tmp_path / "conftest.py").write_text(
        "import rerun_budget\n\n"
        "def pytest_configure(config):\n"
        "    rerun_budget.register(config)\n"
    )
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    for n in range(flaky):
        (tmp_path / f"test_flaky_{n}.py").write_text(_FLAKY_TEST.format(n=n))
    (tmp_path / "test_steady.py").write_text("def test_steady():\n    pass\n")
    summary = tmp_path / "step_summary.md"
    env = os.environ.copy()
    for name in ("PYTEST_ADDOPTS", "INKYPI_MAX_TEST_RERUNS"):
        env.pop(name, None)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env["GITHUB_STEP_SUMMARY"] = str(summary)
    if budget is not None:
        env["INKYPI_MAX_TEST_RERUNS"] = budget
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "pytest_rerunfailures", "-q", *extra],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    written = summary.read_text() if summary.exists() else ""
    return result.returncode, result.stdout + result.stderr, written


def test_a_retried_test_is_reported_with_its_first_failure(tmp_path: Path) -> None:
    code, output, summary = _run(tmp_path, flaky=1)

    assert code == 0, output
    assert "tests that passed only on a retry" in output
    assert "RETRIED test_flaky_0.py::test_flaky_0" in output
    assert "AssertionError: first attempt of 0 failed" in output
    assert "1 of at most 2 allowed retries used." in output
    assert "<code>test_flaky_0.py::test_flaky_0</code>" in summary
    assert "first attempt of 0 failed" in summary


def test_more_retried_tests_than_the_budget_fail_the_run(tmp_path: Path) -> None:
    code, output, summary = _run(tmp_path, flaky=3)

    assert code == pytest.ExitCode.TESTS_FAILED, output
    assert "4 passed, 3 rerun" in output
    assert "3 tests needed a retry; at most 2 may" in output
    assert "Failing the run" in summary


def test_budget_comes_from_the_environment(tmp_path: Path) -> None:
    code, output, _ = _run(tmp_path, flaky=1, budget="0")

    assert code == pytest.ExitCode.TESTS_FAILED, output
    assert "1 tests needed a retry; at most 0 may" in output


def test_a_clean_run_prints_nothing_extra(tmp_path: Path) -> None:
    code, output, summary = _run(tmp_path, flaky=0)

    assert code == 0, output
    assert "passed only on a retry" not in output
    assert summary == ""


def test_retries_on_xdist_workers_are_counted_once(tmp_path: Path) -> None:
    code, output, _ = _run(tmp_path, 1, "-p", "xdist.plugin", "-n", "2")

    assert code == 0, output
    assert output.count("RETRIED test_flaky_0.py::test_flaky_0") == 1
    assert "1 of at most 2 allowed retries used." in output


def test_invalid_budget_is_a_usage_error(tmp_path: Path) -> None:
    code, output, _ = _run(tmp_path, flaky=0, budget="lots")

    assert code == pytest.ExitCode.USAGE_ERROR, output
    assert "INKYPI_MAX_TEST_RERUNS must be a whole number" in output
