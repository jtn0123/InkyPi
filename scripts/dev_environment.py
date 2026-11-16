#!/usr/bin/env python3
"""Check or hash-verify sync the active development environment, without network checks."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "install/requirements-dev.txt"
# The uv pin the Pi installer uses; check_install_pins.py keeps it equal (same
# version and hashes) to the uv in the dev lock.
UV_LOCK = ROOT / "install/uv-requirements.txt"
SYNC_COMMAND = "source scripts/venv.sh"
# pyproject.toml's requires-python. tests/unit/test_dev_environment.py keeps
# the two in step, and scripts/venv.sh builds the venv with this version.
SUPPORTED_PYTHON = (3, 13)


def lock_fingerprint(root: Path = ROOT) -> str:
    """Fingerprint what ``--sync`` installs: the dev requirements and Python.

    pyproject.toml and uv.lock are left out on purpose. Every release bumps
    InkyPi's own version in both, which made each checkout look out of sync
    (and scripts/test.sh refuse to run) though no dependency had changed.
    The requirements file is exported with --no-emit-project, so it carries
    no project version, and CI's drift check keeps it in step with uv.lock.
    """
    digest = hashlib.sha256()
    digest.update((root / LOCK.relative_to(ROOT)).read_bytes())
    digest.update(f"{sys.version_info[:2]}:{sys.platform}".encode())
    return digest.hexdigest()


def interpreter_problem(version: tuple[int, ...] = sys.version_info[:2]) -> str:
    """Why this interpreter can't hold the dev environment, or "" if it can.

    The lock pins wheels for the supported version only, so syncing another
    Python installs a different set of packages than CI and the Pi run.
    """
    if tuple(version[:2]) == SUPPORTED_PYTHON:
        return ""
    want = ".".join(map(str, SUPPORTED_PYTHON))
    have = ".".join(map(str, version[:2]))
    return (
        f"InkyPi needs Python {want}, but {sys.executable} is Python {have}. "
        f"Remove the environment (rm -rf .venv) and run: {SYNC_COMMAND}"
    )


def installed_drift(lock: Path = LOCK) -> list[str]:
    try:
        from packaging.requirements import Requirement
        from packaging.version import Version
    except ImportError:
        return ["packaging: missing (environment has not been initialized)"]
    problems = []
    for line in lock.read_text().splitlines():
        line = line.strip().removesuffix("\\").strip()
        if not line or line.startswith(("#", "--")):
            continue
        requirement = Requirement(line)
        if requirement.marker and not requirement.marker.evaluate():
            continue
        try:
            version = importlib.metadata.version(requirement.name)
        except importlib.metadata.PackageNotFoundError:
            problems.append(f"{requirement.name}: missing")
            continue
        if Version(version) not in requirement.specifier:
            problems.append(
                f"{requirement.name}: installed {version}, expected {requirement.specifier}"
            )
    return problems


def check_environment(
    stamp: Path, fingerprint: str, *, require_stamp: bool = False
) -> list[str]:
    """What keeps this environment from matching the lock.

    CI installs the hashed requirements directly, with no stamp, so a missing
    stamp is only a problem with *require_stamp*: before another checkout's
    venv is shared, it must have been synced from exactly this lock.
    """
    problems = installed_drift()
    if stamp.exists():
        try:
            if json.loads(stamp.read_text()).get("fingerprint") != fingerprint:
                problems.append("lock fingerprint changed since the last verified sync")
        except (ValueError, OSError, AttributeError):
            problems.append("environment sync record is unreadable")
    elif require_stamp:
        problems.append("no record of a hash-verified sync of this lock")
    return problems


def sync_commands(python: str, *, uv_installed: bool) -> list[list[str]]:
    """The commands ``--sync`` runs, in order.

    A fresh venv has only pip, and pip takes minutes over the dev lock. So
    pip first installs uv alone, hash-checked from the installer's pin, and
    uv installs the lock. Both steps require hashes.
    """
    commands = []
    if not uv_installed:
        commands.append(
            [python, "-m", "pip", "install", "--require-hashes", "-r", str(UV_LOCK)]
        )
    commands.append(
        [
            python,
            "-m",
            "uv",
            "--no-config",
            "pip",
            "install",
            "--python",
            python,
            "--require-hashes",
            "-r",
            str(LOCK),
        ]
    )
    return commands


def _uv_installed() -> bool:
    try:
        importlib.metadata.version("uv")
    except importlib.metadata.PackageNotFoundError:
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--sync",
        action="store_true",
        help="Install committed, hash-verified dev requirements",
    )
    mode.add_argument(
        "--require-stamp",
        action="store_true",
        help=(
            "Also fail unless this environment was synced from exactly this lock "
            "on the supported Python (scripts/venv.sh checks this before a "
            "worktree shares the main checkout's venv)"
        ),
    )
    args = parser.parse_args()
    if args.sync and sys.prefix == sys.base_prefix:
        print(f"Use a virtual environment. Run: {SYNC_COMMAND}", file=sys.stderr)
        return 1
    # Only sync and sharing refuse: the plain check also runs under the weekly
    # next-Python CI job, which installs the same pins on purpose.
    if (args.sync or args.require_stamp) and (problem := interpreter_problem()):
        print(problem, file=sys.stderr)
        return 1
    fingerprint = lock_fingerprint()
    stamp = Path(sys.prefix) / ".inkypi-dev-lock.json"
    if args.sync:
        for command in sync_commands(sys.executable, uv_installed=_uv_installed()):
            subprocess.run(command, cwd=ROOT, check=True)
        problems = installed_drift()
        if not problems:
            stamp.write_text(json.dumps({"fingerprint": fingerprint}) + "\n")
    else:
        problems = check_environment(
            stamp, fingerprint, require_stamp=args.require_stamp
        )
    if problems:
        print("Development environment is out of sync:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        print(f"Run: {SYNC_COMMAND}", file=sys.stderr)
        return 1
    print("Development environment matches committed requirements.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
