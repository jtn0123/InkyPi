#!/usr/bin/env python3
"""Check the installer's own requirement files against uv.lock.

``install/bootstrap-requirements.txt`` (pip, setuptools, wheel, packaging),
``install/uv-requirements.txt`` (uv) and ``install/ws-requirements.txt`` (the
Waveshare GPIO libraries) are installed as root during install and update, but
they aren't exported from uv.lock, so a Dependabot bump of the lock never
touches them. This fails when:

- a package they pin is also in uv.lock at a different version, or with a
  hash the lock doesn't list for that version;
- two of them pin the same package at different versions.

Exit codes: 0 consistent, 1 a mismatch was found.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL_FILES = tuple(
    ROOT / "install" / name
    for name in (
        "bootstrap-requirements.txt",
        "uv-requirements.txt",
        "ws-requirements.txt",
    )
)
LOCK = ROOT / "uv.lock"

_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==(\S+)")
_HASH = re.compile(r"--hash=(sha256:[0-9a-f]{64})")


def _normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def read_pins(text: str) -> dict[str, tuple[str, set[str]]]:
    """Return ``{package: (version, hashes)}`` for a hashed requirements file."""
    pins: dict[str, tuple[str, set[str]]] = {}
    current: str | None = None
    for line in text.splitlines():
        match = _PIN.match(line)
        if match:
            current = _normalise(match[1])
            pins[current] = (match[2], set())
        if current is not None:
            pins[current][1].update(_HASH.findall(line))
    return pins


def read_lock(text: str) -> dict[str, tuple[str, set[str]]]:
    """Return ``{package: (version, hashes)}`` from uv.lock."""
    locked: dict[str, tuple[str, set[str]]] = {}
    for package in tomllib.loads(text).get("package", []):
        files = [package.get("sdist", {}), *package.get("wheels", [])]
        hashes = {f["hash"] for f in files if "hash" in f}
        locked[_normalise(package["name"])] = (str(package.get("version")), hashes)
    return locked


def check(
    files: dict[str, dict[str, tuple[str, set[str]]]],
    locked: dict[str, tuple[str, set[str]]],
) -> list[str]:
    """Return one problem line per mismatch."""
    problems = []
    seen: dict[str, tuple[str, str]] = {}
    for source, pins in files.items():
        for package, (version, hashes) in pins.items():
            if package in seen and seen[package][0] != version:
                other_version, other_source = seen[package]
                problems.append(
                    f"{source}: {package}=={version}, but {other_source} pins "
                    f"{other_version}"
                )
            seen.setdefault(package, (version, source))
            if package not in locked:
                continue
            lock_version, lock_hashes = locked[package]
            if version != lock_version:
                problems.append(
                    f"{source}: {package}=={version}, but uv.lock has {lock_version}"
                )
            elif unknown := sorted(hashes - lock_hashes):
                problems.append(
                    f"{source}: {package}=={version} has hashes uv.lock doesn't "
                    f"list: {', '.join(unknown)}"
                )
    return problems


def main() -> int:
    files = {
        path.relative_to(ROOT).as_posix(): read_pins(path.read_text(encoding="utf-8"))
        for path in INSTALL_FILES
    }
    problems = check(files, read_lock(LOCK.read_text(encoding="utf-8")))
    for problem in problems:
        print(f"ERROR: {problem}", file=sys.stderr)
    if problems:
        print(
            "Update the install file's pin and hashes to match uv.lock "
            "(the hashes are in the lock's entry for that package).",
            file=sys.stderr,
        )
        return 1
    print("    OK — installer requirement files agree with uv.lock.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
