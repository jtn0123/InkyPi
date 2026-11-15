"""CI installs dependencies once per job, one way, and runs each check once.

Jobs used to copy the same setup-python + pip block (some installed
everything twice: once system-wide, once into .venv), shellcheck ran in two
places at two severities, and the license check installed an unpinned
pip-licenses. These guards keep those from creeping back.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github/workflows"
ACTION = ROOT / ".github/actions/setup-python-deps/action.yml"
LOCAL_ACTION = "./.github/actions/setup-python-deps"
#: Installs the runtime lockfile with Debian Trixie's own python3 and pip in a
#: container, as the Pi does, so it deliberately bypasses the shared action.
CONTAINER_SMOKE_JOB = "smoke"


def _steps(path: Path) -> dict[str, list[dict[str, object]]]:
    workflow = yaml.safe_load(path.read_text())
    assert isinstance(workflow, dict)
    result = {}
    for name, job in workflow["jobs"].items():
        steps = job.get("steps", [])
        assert isinstance(steps, list)
        result[str(name)] = steps
    return result


def _ci_workflows() -> list[Path]:
    return [WORKFLOWS / "ci.yml", WORKFLOWS / "preflash-macos-weekly.yml"]


def test_action_installs_hashed_lockfiles_into_venv() -> None:
    action = yaml.safe_load(ACTION.read_text())
    assert action["runs"]["using"] == "composite"
    runs = "\n".join(step.get("run", "") for step in action["runs"]["steps"])
    # uv itself and every lockfile are hash-checked, as in install/install.sh.
    assert "--require-hashes -r install/uv-requirements.txt" in runs
    assert "uv pip install" in runs and "--require-hashes" in runs
    assert "python -m venv .venv" in runs
    assert "pip check" in runs
    # Later steps (and scripts/preflash_validate.sh) use the .venv.
    assert '"$PWD/.venv/bin" >> "$GITHUB_PATH"' in runs


def test_jobs_install_python_dependencies_only_through_the_action() -> None:
    for path in _ci_workflows():
        for job, steps in _steps(path).items():
            if job == CONTAINER_SMOKE_JOB and path.name == "ci.yml":
                continue
            setups = [step for step in steps if step.get("uses") == LOCAL_ACTION]
            raw = [
                step["run"]
                for step in steps
                if "pip install -r install/requirements" in str(step.get("run", ""))
            ]
            assert not raw, f"{path.name}:{job} installs lockfiles itself: {raw}"
            assert len(setups) <= 1, f"{path.name}:{job} sets up Python twice"


def test_preflash_jobs_get_their_venv_from_the_action() -> None:
    # scripts/preflash_validate.sh refuses to run without .venv; the action
    # is what creates it, so every job that runs the script must use it.
    for path in _ci_workflows():
        for job, steps in _steps(path).items():
            runs = " ".join(str(step.get("run", "")) for step in steps)
            if "scripts/preflash_validate.sh" not in runs:
                continue
            assert any(
                step.get("uses") == LOCAL_ACTION for step in steps
            ), f"{path.name}:{job} runs preflash_validate.sh without the setup action"


def _calls_shellcheck(run: str) -> bool:
    # A command, not a `# shellcheck disable=...` directive in a run block.
    return any(
        re.search(r"(?:^|[;&|(]\s*)shellcheck\b", line.strip())
        for line in run.splitlines()
        if not line.strip().startswith("#")
    )


def test_shellcheck_runs_once_from_lint() -> None:
    lint = (ROOT / "scripts/lint.sh").read_text()
    assert "scripts/check_shell.sh" in lint
    assert "--severity" not in (ROOT / "scripts/check_shell.sh").read_text()
    assert _calls_shellcheck("shellcheck install/*.sh")
    assert not _calls_shellcheck("# shellcheck disable=SC1091\nsource x")
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for job, steps in _steps(path).items():
            for step in steps:
                assert not _calls_shellcheck(
                    str(step.get("run", ""))
                ), f"{path.name}:{job} runs shellcheck outside scripts/lint.sh"


def test_license_check_installs_nothing() -> None:
    commands = [
        line.strip()
        for line in (ROOT / "scripts/check_licenses.sh").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith(("#", "echo"))
    ]
    assert not any("pip install" in line for line in commands), commands
    assert any(line.startswith("python -m piplicenses") for line in commands)
    lint_runs = [
        str(step.get("run", "")) for step in _steps(WORKFLOWS / "ci.yml")["lint"]
    ]
    assert "scripts/check_licenses.sh" in lint_runs
    assert not any("pip install" in run for run in lint_runs)
    # The pin the script relies on: an exact version, with hashes.
    dev_lock = (ROOT / "install/requirements-dev.txt").read_text()
    assert re.search(
        r"^pip-licenses==[0-9]+(\.[0-9]+)+ \\\n\s+--hash=sha256:[0-9a-f]{64}",
        dev_lock,
        re.M,
    )
