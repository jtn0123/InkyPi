"""The aggregate status must await and enforce every ordinary mandatory CI job."""

import json
import re
import shlex
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
ADVISORY_JOBS = {"sonarcloud"}
EVENT_ONLY_JOBS = {"soak-nightly", "mutation-nightly"}


def _jobs() -> dict[str, dict[str, object]]:
    data = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    assert isinstance(data, dict)
    jobs = data["jobs"]
    assert isinstance(jobs, dict)
    result: dict[str, dict[str, object]] = {}
    for name, job in jobs.items():
        assert isinstance(name, str)
        assert isinstance(job, dict)
        assert all(isinstance(key, str) for key in job)
        result[name] = dict(job)
    return result


def _mandatory_jobs(jobs: dict[str, dict[str, object]]) -> set[str]:
    mandatory = set()
    for name, job in jobs.items():
        if name == "ci-gate" or name in ADVISORY_JOBS or job.get("if"):
            continue
        optional = job.get("continue-on-error", False)
        assert isinstance(
            optional, bool
        ), "Classify dynamic optional-job policies explicitly"
        if not optional:
            mandatory.add(name)
    return mandatory


def _needs(gate: dict[str, object]) -> list[str]:
    needs = gate["needs"]
    assert isinstance(needs, list)
    assert all(isinstance(name, str) for name in needs)
    return list(needs)


def _gate_script(gate: dict[str, object]) -> str:
    steps = gate["steps"]
    assert isinstance(steps, list)
    runs = [step["run"] for step in steps if isinstance(step, dict) and "run" in step]
    assert len(runs) == 1
    assert isinstance(runs[0], str)
    return runs[0]


def _run_gate(faults: dict[str, str | None]) -> subprocess.CompletedProcess[str]:
    gate = _jobs()["ci-gate"]
    results = {name: {"result": "success"} for name in _needs(gate)}
    for name, state in faults.items():
        if state is None:
            results.pop(name, None)
        else:
            results[name] = {"result": state}
    script = _gate_script(gate).replace("${{ toJSON(needs) }}", json.dumps(results))
    return subprocess.run(
        ["bash", "-e", "-c", script], capture_output=True, text=True, timeout=15
    )


def test_gate_dependencies_and_success_loop_cover_mandatory_jobs() -> None:
    jobs = _jobs()
    gate = jobs["ci-gate"]
    mandatory = _mandatory_jobs(jobs)
    conditional = {name for name, job in jobs.items() if job.get("if")}
    assert conditional == EVENT_ONLY_JOBS | ADVISORY_JOBS | {"ci-gate"}
    assert gate["if"] == "always()"
    assert set(_needs(gate)) == mandatory | ADVISORY_JOBS
    loops = re.findall(r"for\s+job\s+in\s+([^;]+);\s*do", _gate_script(gate))
    assert len(loops) == 1
    required = shlex.split(loops[0])
    assert len(required) == len(set(required))
    assert set(required) == mandatory


def test_matrix_and_step_conditions_do_not_make_a_job_optional() -> None:
    jobs: dict[str, dict[str, object]] = {
        "matrix": {
            "strategy": {"matrix": {"os": ["ubuntu-latest", "macos-latest"]}},
            "steps": [{"if": "runner.os == 'Linux'", "run": "test-command"}],
        },
        "event-only": {"if": "github.event_name == 'schedule'"},
        "optional": {"continue-on-error": True},
    }
    assert _mandatory_jobs(jobs) == {"matrix"}


@pytest.mark.parametrize("job", ["flake-detection", "preflash-validate", "tests"])
@pytest.mark.parametrize("state", ["failure", "cancelled", "skipped", None])
def test_real_gate_rejects_missing_or_unsuccessful_mandatory_jobs(
    job: str, state: str | None
) -> None:
    result = _run_gate({job: state})
    assert result.returncode == 1, result.stdout + result.stderr
    assert f"Required job '{job}' did not succeed" in result.stdout


@pytest.mark.parametrize("state", ["success", "failure", "skipped", "cancelled"])
def test_real_gate_preserves_advisory_sonar_and_event_only_exclusions(
    state: str,
) -> None:
    result = _run_gate({"sonarcloud": state})
    assert result.returncode == 0, result.stdout + result.stderr
    assert "All required CI checks passed." in result.stdout
    assert not (set(_needs(_jobs()["ci-gate"])) & EVENT_ONLY_JOBS)
