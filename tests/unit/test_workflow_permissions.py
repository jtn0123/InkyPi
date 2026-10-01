"""Local reusable workflows cannot elevate the caller's token permissions."""

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github/workflows"
LEVELS = {"none": 0, "read": 1, "write": 2}


def _workflow(path: Path) -> dict[str, object]:
    value = yaml.safe_load(path.read_text())
    assert isinstance(value, dict)
    assert all(isinstance(key, (str, bool)) for key in value)
    # PyYAML treats GitHub's `on` key as a YAML 1.1 boolean; this test only
    # consumes jobs and permissions, whose keys remain strings.
    return {str(key): item for key, item in value.items()}


def _jobs(workflow: dict[str, object]) -> dict[str, dict[str, object]]:
    value = workflow["jobs"]
    assert isinstance(value, dict)
    result: dict[str, dict[str, object]] = {}
    for name, job in value.items():
        assert isinstance(name, str) and isinstance(job, dict)
        assert all(isinstance(key, str) for key in job)
        result[name] = dict(job)
    return result


def _permissions(value: object) -> dict[str, int]:
    assert isinstance(value, dict), "Local workflow calls must declare permissions"
    result = {}
    for scope, level in value.items():
        assert isinstance(scope, str) and isinstance(level, str)
        assert level in LEVELS
        result[scope] = LEVELS[level]
    return result


def _local_calls() -> list[tuple[Path, str]]:
    result = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for name, job in _jobs(_workflow(path)).items():
            target = job.get("uses")
            if isinstance(target, str) and target.startswith("./.github/workflows/"):
                result.append((path, name))
    assert result, "Expected release/install reusable workflow calls"
    return result


@pytest.mark.parametrize("path,job_name", _local_calls())
def test_local_reusable_workflow_permissions(path: Path, job_name: str) -> None:
    caller = _workflow(path)
    job = _jobs(caller)[job_name]
    allowed = _permissions(job.get("permissions", caller.get("permissions")))
    target = job["uses"]
    assert isinstance(target, str)
    callee = _workflow(ROOT / target.removeprefix("./"))
    requirements = [callee.get("permissions")]
    requirements.extend(
        child["permissions"]
        for child in _jobs(callee).values()
        if "permissions" in child
    )
    for required in requirements:
        for scope, level in _permissions(required).items():
            assert allowed.get(scope, 0) >= level, (
                f"{path.name}:{job_name} calls {target}, which requests "
                f"{scope} level {level}, but the caller allows "
                f"{allowed.get(scope, 0)}"
            )
