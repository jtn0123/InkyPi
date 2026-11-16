#!/usr/bin/env python3
"""Narrow PR mutation gate: a few hand-picked mutants that tests must catch.

For each mutant, in a fresh copy of the repository:

1. Run the mutant's commands on the unmutated code. Every one must pass. If
   one fails, its exit status would say nothing about the mutant (an import
   error or a missing tool fails the same way a caught bug does), so the
   gate reports the mutant as broken and fails.
2. Apply the mutation and run the commands again. The mutant is killed when
   at least one command fails, and survives when they all pass.

The gate fails when any mutant survives or is broken. A mutant marked
``linux_only`` is reported as skipped on other systems, never as killed.
``scripts/preflash_validate.sh`` runs it when ``INKYPI_VALIDATE_MUTATION=1``,
which CI's ``preflash-validate`` job sets.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Mutant:
    name: str
    file: str
    old: str
    new: str
    commands: tuple[tuple[str, ...], ...]
    linux_only: bool = False


@dataclass(frozen=True)
class MutantResult:
    name: str
    status: str  # "killed", "survived", "broken" or "skipped"
    detail: str = ""


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path(sys.executable)

MUTANTS: tuple[Mutant, ...] = (
    Mutant(
        name="cache-hit-inverted",
        file="src/refresh_task/refresh_cycle.py",
        old="        used_cached = self.display_pipeline.panel_shows(\n",
        new="        used_cached = not self.display_pipeline.panel_shows(\n",
        commands=(
            (
                str(PYTHON),
                "-m",
                "pytest",
                "-q",
                "tests/unit/test_refresh_task_helpers.py",
                "tests/unit/test_refresh_policy.py",
                "tests/integration/test_unchanged_render_skip.py",
            ),
        ),
    ),
    Mutant(
        name="retry-count-off-by-one",
        file="src/refresh_task/executor.py",
        old="        attempts = max(1, retries + 1)\n",
        new="        attempts = max(1, retries)\n",
        commands=(
            (
                str(PYTHON),
                "-m",
                "pytest",
                "-q",
                "tests/unit/test_refresh_policy.py",
                "tests/unit/test_plugin_isolation.py",
            ),
        ),
    ),
    Mutant(
        name="unchanged-display-skip-broken",
        file="src/display/display_manager.py",
        old="        return image_hash == self._last_image_hash and key == self._last_settings_key\n",
        new="        return image_hash != self._last_image_hash and key == self._last_settings_key\n",
        commands=(
            (
                str(PYTHON),
                "-m",
                "pytest",
                "-q",
                "tests/unit/test_display_manager.py",
                "tests/unit/test_display_manager_coverage.py",
            ),
        ),
    ),
    Mutant(
        name="install-idempotency-assert-weakened",
        file="scripts/preflash_smoke.py",
        old="            if lines.count(overlay) != 1:\n",
        new="            if lines.count(overlay) != 2:\n",
        commands=((str(PYTHON), "scripts/preflash_smoke.py", "install-idempotency"),),
        # The smoke drives GNU sed, so it refuses to run anywhere but Linux.
        linux_only=True,
    ),
)


def _copy_repo(source: Path, destination: Path) -> None:
    shutil.copytree(
        source,
        destination,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(
            ".git",
            ".venv",
            "__pycache__",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
            "node_modules",
            "mutants",
            "htmlcov",
            "coverage.xml",
            "runtime",
        ),
    )


def _apply_mutation(repo_root: Path, mutant: Mutant) -> None:
    target = repo_root / mutant.file
    original = target.read_text(encoding="utf-8")
    if mutant.old not in original:
        raise RuntimeError(f"{mutant.name}: target snippet not found in {mutant.file}")
    mutated = original.replace(mutant.old, mutant.new, 1)
    target.write_text(mutated, encoding="utf-8")
    # The baseline run compiled the unmutated file. Drop its bytecode so a
    # same-length mutation (== to !=) cannot be masked by a stale .pyc.
    cached = Path(importlib.util.cache_from_source(str(target)))
    cached.unlink(missing_ok=True)


def _run(repo_root: Path, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root / "src")
    env["INKYPI_ENV"] = "dev"
    env["INKYPI_NO_REFRESH"] = "1"
    return subprocess.run(
        list(command),
        cwd=repo_root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )


def _tail(output: str, lines: int = 15) -> str:
    return "\n".join(output.strip().splitlines()[-lines:])


def check_mutant(mutant: Mutant, repo_root: Path = REPO_ROOT) -> MutantResult:
    """Run one mutant's baseline and mutated runs in a fresh repository copy."""
    if mutant.linux_only and sys.platform != "linux":
        return MutantResult(mutant.name, "skipped", "needs Linux")
    with tempfile.TemporaryDirectory(prefix=f"inkypi-mutant-{mutant.name}-") as tmp:
        repo_copy = Path(tmp) / "repo"
        _copy_repo(repo_root, repo_copy)
        for command in mutant.commands:
            proc = _run(repo_copy, command)
            if proc.returncode != 0:
                return MutantResult(
                    mutant.name,
                    "broken",
                    f"`{' '.join(command)}` exited {proc.returncode} on the "
                    f"unmutated code:\n{_tail(proc.stdout)}",
                )
        _apply_mutation(repo_copy, mutant)
        for command in mutant.commands:
            proc = _run(repo_copy, command)
            if proc.returncode != 0:
                return MutantResult(
                    mutant.name, "killed", f"exit {proc.returncode}: {command[-1]}"
                )
    return MutantResult(mutant.name, "survived")


def main(mutants: Sequence[Mutant] = MUTANTS, repo_root: Path = REPO_ROOT) -> int:
    failures: list[MutantResult] = []
    for mutant in mutants:
        started = time.monotonic()
        result = check_mutant(mutant, repo_root)
        elapsed = time.monotonic() - started
        suffix = (
            f" ({result.detail})" if result.detail and result.status != "broken" else ""
        )
        print(f"{mutant.name}: {result.status}{suffix} in {elapsed:.1f}s", flush=True)
        if result.status in ("survived", "broken"):
            failures.append(result)

    for result in failures:
        if result.status == "broken":
            print(
                f"{result.name}: the commands fail without the mutation, so the "
                f"gate cannot tell whether the tests catch it.\n{result.detail}",
                file=sys.stderr,
            )
        else:
            print(
                f"{result.name}: no command failed with the mutation applied. "
                "Add or fix a test so it catches this bug.",
                file=sys.stderr,
            )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
