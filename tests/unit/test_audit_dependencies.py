"""scripts/audit_dependencies.sh, and when CI runs it strictly.

pip-audit checks the locked files against a live advisory feed. A new
advisory used to fail every pull request, including docs-only ones, so CI
now fails only a pull request that changes a dependency file (and the
nightly run); other runs get a warning.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "audit_dependencies.sh"
CI_YAML = REPO_ROOT / ".github" / "workflows" / "ci.yml"

FINDING = (
    '{"dependencies": [{"name": "pillow", "version": "11.0.0", "vulns": '
    '[{"id": "GHSA-test", "fix_versions": ["11.1.0"]}]}]}'
)

# Stands in for `python`: `-m pip_audit` writes a report for the file given
# with -r and fails for $VULN_FILE (with a finding) or $BROKEN_FILE (with no
# report, as when the advisory feed can't be reached). Anything else runs
# the real interpreter.
FAKE_PYTHON = """#!/usr/bin/env bash
if [ "$1" = "-m" ] && [ "$2" = "pip_audit" ]; then
    out=""
    req=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --output) out="$2"; shift ;;
            -r) req="$2"; shift ;;
        esac
        shift
    done
    if [ "$req" = "${BROKEN_FILE:-}" ]; then
        exit 1
    fi
    if [ "$req" = "${VULN_FILE:-}" ]; then
        printf '%s' "$FINDING" > "$out"
        exit 1
    fi
    printf '%s' '{"dependencies": []}' > "$out"
    exit 0
fi
exec "$REAL_PYTHON" "$@"
"""


def _run_script(
    tmp_path: Path, *args: str, **env: str
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    fake = bin_dir / "python"
    fake.write_text(FAKE_PYTHON)
    fake.chmod(0o755)
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "REAL_PYTHON": sys.executable,
            "FINDING": FINDING,
            **env,
        },
        capture_output=True,
        text=True,
        check=False,
    )


def test_no_findings_passes_in_strict_mode(tmp_path: Path) -> None:
    result = _run_script(tmp_path, "--strict")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "no known vulnerabilities" in result.stdout
    reports = sorted(p.name for p in (tmp_path / "artifacts/security").iterdir())
    assert reports == [
        f"pip-audit-{name}.json" for name in ("bootstrap", "dev", "runtime", "uv", "ws")
    ]


def test_a_finding_fails_strict_mode_and_names_the_fix(tmp_path: Path) -> None:
    result = _run_script(tmp_path, "--strict", VULN_FILE="install/requirements.txt")
    assert result.returncode == 1
    assert "runtime: pillow 11.0.0: GHSA-test (fixed in: 11.1.0)" in result.stdout
    assert "::error title=Known vulnerabilities::" in result.stdout


def test_a_finding_only_warns_without_strict(tmp_path: Path) -> None:
    result = _run_script(tmp_path, VULN_FILE="install/uv-requirements.txt")
    assert result.returncode == 0
    assert "uv: pillow 11.0.0: GHSA-test (fixed in: 11.1.0)" in result.stdout
    assert "::warning title=Known vulnerabilities (not blocking)::" in result.stdout


def test_an_audit_that_cannot_finish_still_fails_strict_mode(tmp_path: Path) -> None:
    result = _run_script(
        tmp_path, "--strict", BROKEN_FILE="install/requirements-dev.txt"
    )
    assert result.returncode == 1
    assert "dev: no report; the audit did not finish" in result.stdout
    # The other files were still audited.
    assert (tmp_path / "artifacts/security/pip-audit-ws.json").is_file()


def test_rejects_unknown_arguments(tmp_path: Path) -> None:
    result = _run_script(tmp_path, "--lenient")
    assert result.returncode == 2
    assert "usage:" in result.stderr


def _audit_step() -> dict[str, Any]:
    ci: dict[str, Any] = yaml.safe_load(CI_YAML.read_text())
    steps: list[dict[str, Any]] = ci["jobs"]["security"]["steps"]
    return next(
        s for s in steps if s.get("name") == "Run pip-audit against hashed lockfiles"
    )


def _strict_mode(tmp_path: Path, event: str, changed: str) -> str:
    """Run the CI step's shell with fakes; return the args the script got."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    git = bin_dir / "git"
    git.write_text('#!/usr/bin/env bash\nprintf "%s" "$CHANGED"\n')
    git.chmod(0o755)
    scripts = tmp_path / "scripts"
    scripts.mkdir(exist_ok=True)
    stub = scripts / "audit_dependencies.sh"
    stub.write_text('#!/usr/bin/env bash\necho "args:[$*]"\n')
    stub.chmod(0o755)
    result = subprocess.run(
        ["bash", "-eo", "pipefail", "-c", _audit_step()["run"]],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "EVENT_NAME": event,
            "CHANGED": changed,
        },
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


@pytest.mark.parametrize(
    ("event", "changed", "expected"),
    [
        ("pull_request", "docs/README.md\nsrc/app.py\n", "args:[]"),
        ("pull_request", "src/app.py\nuv.lock\n", "args:[--strict]"),
        ("pull_request", "install/requirements.txt\n", "args:[--strict]"),
        ("pull_request", "install/ws-requirements.txt\n", "args:[--strict]"),
        ("pull_request", "install/requirements.in.bak\n", "args:[]"),
        ("push", "uv.lock\n", "args:[]"),
        ("schedule", "", "args:[--strict]"),
        ("workflow_dispatch", "", "args:[--strict]"),
    ],
)
def test_ci_is_strict_only_where_a_finding_is_actionable(
    tmp_path: Path, event: str, changed: str, expected: str
) -> None:
    assert _strict_mode(tmp_path, event, changed) == expected


def test_ci_checkout_can_see_the_pull_requests_base() -> None:
    ci: dict[str, Any] = yaml.safe_load(CI_YAML.read_text())
    checkout = ci["jobs"]["security"]["steps"][0]
    assert checkout["uses"].startswith("actions/checkout@")
    assert checkout["with"]["fetch-depth"] == 2
