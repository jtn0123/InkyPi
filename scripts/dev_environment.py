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
SYNC_COMMAND = "source scripts/venv.sh"


def lock_fingerprint(root: Path = ROOT) -> str:
    digest = hashlib.sha256()
    for name in (
        "pyproject.toml",
        "uv.lock",
        "install/requirements-dev.in",
        "install/requirements-dev.txt",
    ):
        digest.update(name.encode())
        digest.update((root / name).read_bytes())
    digest.update(f"{sys.version_info[:2]}:{sys.platform}".encode())
    return digest.hexdigest()


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


def check_environment(stamp: Path, fingerprint: str) -> list[str]:
    problems = installed_drift()
    if stamp.exists():
        try:
            if json.loads(stamp.read_text()).get("fingerprint") != fingerprint:
                problems.append("lock fingerprint changed since the last verified sync")
        except (ValueError, OSError, AttributeError):
            problems.append("environment sync record is unreadable")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Install committed, hash-verified dev requirements",
    )
    args = parser.parse_args()
    if args.sync and sys.prefix == sys.base_prefix:
        print(f"Use a virtual environment. Run: {SYNC_COMMAND}", file=sys.stderr)
        return 1
    fingerprint = lock_fingerprint()
    stamp = Path(sys.prefix) / ".inkypi-dev-lock.json"
    if args.sync:
        # pip is available in a fresh venv; uv, when installed, is much faster.
        try:
            importlib.metadata.version("uv")
            command = [
                sys.executable,
                "-m",
                "uv",
                "--no-config",
                "pip",
                "install",
                "--python",
                sys.executable,
            ]
        except importlib.metadata.PackageNotFoundError:
            command = [sys.executable, "-m", "pip", "install"]
        subprocess.run(
            command + ["--require-hashes", "-r", str(LOCK)], cwd=ROOT, check=True
        )
        problems = installed_drift()
        if not problems:
            stamp.write_text(json.dumps({"fingerprint": fingerprint}) + "\n")
    else:
        problems = check_environment(stamp, fingerprint)
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
