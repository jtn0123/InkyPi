#!/usr/bin/env python3

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Mutant:
    name: str
    file: str
    old: str
    new: str
    commands: tuple[tuple[str, ...], ...]


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path(sys.executable)

MUTANTS: tuple[Mutant, ...] = (
    Mutant(
        name="cache-hit-inverted",
        file="src/refresh_task.py",
        old="        used_cached = image_hash == latest_refresh.image_hash\n",
        new="        used_cached = image_hash != latest_refresh.image_hash\n",
        commands=(
            (
                str(PYTHON),
                "-m",
                "pytest",
                "-q",
                "tests/unit/test_refresh_task_helpers.py",
                "tests/unit/test_refresh_policy.py",
            ),
        ),
    ),
    Mutant(
        name="retry-count-off-by-one",
        file="src/refresh_task.py",
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
        old="        if image_hash == self._last_image_hash:\n",
        new="        if image_hash != self._last_image_hash:\n",
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
    ),
)


def _copy_repo(destination: Path) -> None:
    shutil.copytree(
        REPO_ROOT,
        destination,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(
            ".git",
            ".venv",
            "__pycache__",
            ".pytest_cache",
            "htmlcov",
            "coverage.xml",
            "mock_display_output",
        ),
    )


def _apply_mutation(repo_root: Path, mutant: Mutant) -> None:
    target = repo_root / mutant.file
    original = target.read_text(encoding="utf-8")
    if mutant.old not in original:
        raise RuntimeError(f"{mutant.name}: target snippet not found in {mutant.file}")
    mutated = original.replace(mutant.old, mutant.new, 1)
    target.write_text(mutated, encoding="utf-8")


def _run_commands(repo_root: Path, mutant: Mutant) -> bool:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root / "src")
    env["INKYPI_ENV"] = "dev"
    env["INKYPI_NO_REFRESH"] = "1"
    for command in mutant.commands:
        proc = subprocess.run(
            list(command),
            cwd=repo_root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if proc.returncode == 0:
            return False
    return True


def main() -> int:
    survivors: list[str] = []
    for mutant in MUTANTS:
        with tempfile.TemporaryDirectory(prefix=f"inkypi-mutant-{mutant.name}-") as tmpdir:
            repo_copy = Path(tmpdir) / "repo"
            _copy_repo(repo_copy)
            _apply_mutation(repo_copy, mutant)
            killed = _run_commands(repo_copy, mutant)
        status = "killed" if killed else "survived"
        print(f"{mutant.name}: {status}")
        if not killed:
            survivors.append(mutant.name)

    if survivors:
        print(
            "Mutation survivors: " + ", ".join(sorted(survivors)),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
