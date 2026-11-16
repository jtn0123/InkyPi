"""The local test runner selects what CI runs, without overloading the machine.

``scripts/test.sh`` hands whole-suite runs to ``scripts/test-fast.sh``, which
runs everything except ``memory`` tests in parallel and then the ``memory``
tests serially. CI's ``tests`` job runs the same script, and the two marker
expressions must add up to ``-m "not container"`` (the ``container`` tests
have their own job), or a clean run stops covering the suite. Checked
statically: collecting the suite three times would make this test slower than
the bug it guards against.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_SH = REPO_ROOT / "scripts" / "test.sh"
TEST_FAST_SH = REPO_ROOT / "scripts" / "test-fast.sh"
CI_YML = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _code(path: Path) -> str:
    """The script without its comment lines, which quote the old flags."""
    return "\n".join(
        line
        for line in path.read_text().splitlines()
        if not line.lstrip().startswith("#")
    )


def _marker_expressions(script: str) -> list[str]:
    return re.findall(r'-m "([^"]+)"', script)


def test_fast_runner_passes_add_up_to_the_ci_selection() -> None:
    passes = _marker_expressions(_code(TEST_FAST_SH))
    assert sorted(passes) == [
        "not container and memory",
        "not container and not memory",
    ]


def _ci_tests_job() -> str:
    """The ``tests:`` job's block in ci.yml, up to the next top-level job."""
    match = re.search(
        r"^  tests:\n(.*?)(?=^  [\w-]+:\n)", CI_YML.read_text(), re.M | re.S
    )
    assert match, "ci.yml has no `tests` job"
    return match.group(1)


def test_ci_tests_job_runs_the_fast_runner_with_coverage() -> None:
    job = "\n".join(
        line
        for line in _ci_tests_job().splitlines()
        if not line.lstrip().startswith("#")
    )
    assert "scripts/test-fast.sh" in job
    assert "INKYPI_TEST_COVERAGE: '1'" in job
    # A second pytest command in the job would run tests outside the two passes.
    assert not re.search(r"(^|\s)(python -m )?pytest\s", job), job


def test_fast_runner_coverage_spans_both_passes() -> None:
    fast = _code(TEST_FAST_SH)
    assert "PARALLEL_COV=(--cov --cov-report= --cov-fail-under=0)" in fast
    # The serial pass appends to the parallel pass's data before reporting,
    # so coverage.xml and the fail_under check see the whole run.
    assert "SERIAL_COV=(--cov --cov-append --cov-report=xml)" in fast


def test_fast_runner_defaults_to_the_whole_tests_tree() -> None:
    assert 'TARGET=("${@:-tests/}")' in _code(TEST_FAST_SH)


def test_runners_cap_the_worker_count() -> None:
    fast = _code(TEST_FAST_SH)
    assert '-n "${INKYPI_TEST_WORKERS:-4}"' in fast
    for script in (TEST_SH, TEST_FAST_SH):
        assert "-n auto" not in _code(script), script.name


def test_whole_suite_runs_go_through_the_fast_runner() -> None:
    script = _code(TEST_SH)
    assert 'exec "${SCRIPT_DIR}/test-fast.sh" "$@"' in script
    # The old lanes ran 4 x 2 workers at once and skipped ~50 files.
    assert "launch_lane" not in script
