"""Every workflow job that runs steps has a timeout.

GitHub's default is six hours, so a hung job would hold a runner (and block
the CI gate or a release) for that long before anyone noticed.
"""

from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github/workflows"


def _step_jobs() -> list[tuple[str, str, dict[str, object]]]:
    found = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        workflow = yaml.safe_load(path.read_text())
        assert isinstance(workflow, dict)
        jobs = workflow.get("jobs")
        assert isinstance(jobs, dict), f"{path.name} has no jobs"
        for name, job in jobs.items():
            assert isinstance(job, dict)
            # A reusable-workflow call can't set timeout-minutes; the jobs in
            # the called workflow are checked in their own file.
            if "uses" in job:
                continue
            found.append((path.name, str(name), job))
    assert found, "no workflow jobs found"
    return found


@pytest.mark.parametrize(
    ("workflow", "job_name", "job"),
    _step_jobs(),
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_job_sets_timeout_minutes(
    workflow: str, job_name: str, job: dict[str, object]
) -> None:
    timeout = job.get("timeout-minutes")
    assert timeout is not None, f"{workflow}: job {job_name!r} has no timeout-minutes"
    # An expression (e.g. matrix-driven) is fine; a literal must be positive,
    # and within GitHub's 6 h cap unless the job runs on our own runner (the
    # Pi soak legitimately runs for a day).
    if isinstance(timeout, int):
        assert timeout > 0, f"{workflow}: {job_name} timeout {timeout}"
        if "self-hosted" not in str(job.get("runs-on", "")):
            assert timeout <= 360, f"{workflow}: {job_name} timeout {timeout}"
