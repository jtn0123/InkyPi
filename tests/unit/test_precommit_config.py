"""The pre-commit hooks check what CI checks, and CI's hook step still matches them.

A commit that passes the local hooks should not fail CI's lint job on
formatting, and CI's "Pre-commit hooks on changed files" step skips hooks by
id, so a renamed hook would silently start (or stop) running there.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG = REPO_ROOT / ".pre-commit-config.yaml"
CI_YML = REPO_ROOT / ".github" / "workflows" / "ci.yml"
LINT_SH = REPO_ROOT / "scripts" / "lint.sh"


def _hooks() -> dict[str, dict[str, Any]]:
    config = yaml.safe_load(CONFIG.read_text())
    return {hook["id"]: hook for repo in config["repos"] for hook in repo["hooks"]}


def _ci_skips() -> set[str]:
    ci = yaml.safe_load(CI_YML.read_text())
    for step in ci["jobs"]["lint"]["steps"]:
        if "pre-commit run" in step.get("run", ""):
            return set(step["env"]["SKIP"].split(","))
    raise AssertionError("CI's lint job no longer runs the pre-commit hooks")


def test_formatter_matches_the_one_ci_enforces() -> None:
    hooks = _hooks()
    assert "black --check src tests scripts" in LINT_SH.read_text()
    assert "black" in hooks
    # ruff-format and Black disagree on ~150 files; running both fights.
    assert "ruff-format" not in hooks


def test_python_tools_run_from_the_pinned_virtualenv() -> None:
    hooks = _hooks()
    for hook_id in ("ruff", "black", "mypy"):
        assert hooks[hook_id]["language"] == "system", hook_id
        assert hooks[hook_id]["entry"].startswith(
            f"scripts/precommit_tool.sh {hook_id}"
        ), hook_id


def test_mypy_hook_checks_src_like_ci() -> None:
    mypy = _hooks()["mypy"]
    # Per-file mypy runs see only the staged files' imports and disagree with
    # lint.sh's whole-package run.
    assert mypy["pass_filenames"] is False
    assert mypy["entry"].split()[2:] == ["src"]


def test_gitleaks_hook_uses_its_own_entry() -> None:
    # Hook args are appended to the hook's entry
    # (`gitleaks git --pre-commit ... --staged`); the old
    # `detect --source=.` args made every commit fail with
    # "unknown flag: --source".
    assert "args" not in _hooks()["gitleaks"]


def test_ci_skips_only_hooks_that_exist() -> None:
    skips = _ci_skips()
    assert skips <= set(_hooks()), skips - set(_hooks())


def test_ci_skips_only_what_is_checked_elsewhere() -> None:
    # ruff/black/mypy: lint.sh. gitleaks: gitleaks.yml.
    # browser-smoke-gate: the browser-smoke job.
    assert _ci_skips() == {"ruff", "black", "mypy", "gitleaks", "browser-smoke-gate"}
    assert (REPO_ROOT / ".github" / "workflows" / "gitleaks.yml").exists()


def test_ci_hook_step_has_the_base_commit() -> None:
    ci = CI_YML.read_text()
    assert "--from-ref HEAD^1 --to-ref HEAD" in ci
    lint_checkout = yaml.safe_load(ci)["jobs"]["lint"]["steps"][0]
    assert lint_checkout["uses"].startswith("actions/checkout@")
    assert lint_checkout["with"]["fetch-depth"] == 2


def test_commit_message_hook_is_installed_by_default() -> None:
    config = yaml.safe_load(CONFIG.read_text())
    assert "commit-msg" in config["default_install_hook_types"]
    assert re.search(r"stages: \[commit-msg\]", CONFIG.read_text())
