#!/usr/bin/env python3
"""Let a hash-pinned requirements file accept verified wheelhouse wheels.

``install/requirements.txt`` pins PyPI's hashes. The release wheelhouse ships
wheels built in CI for the Pi (e.g. ``numpy-*-linux_armv7l.whl``) whose hashes
PyPI never published, so ``--require-hashes`` rejects them and the installer
falls back to compiling numpy, Pillow and friends from source on the Pi. On a
Pi Zero 2 W that build exhausts memory and can stall the board long enough for
the hardware watchdog to reset it mid-update.

This writes a copy of the requirements file in which every ``name==version``
pin that has a matching wheel in the wheelhouse manifest also accepts that
wheel's sha256. Only hashes from the manifest are added, and the caller only
runs this after ``sha256sum -c`` has verified every extracted wheel against
that manifest, so hash enforcement stays on for every package.

Usage:
    python3 install/_wheelhouse_hashes.py REQUIREMENTS MANIFEST OUTPUT

Prints the number of pins extended. Exit status 0 on success, 2 on bad input.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_PIN = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)==(?P<version>[^\s;\\]+)")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def normalize(name: str) -> str:
    """PEP 503 project-name normalization."""
    return re.sub(r"[-_.]+", "-", name).lower()


def manifest_hashes(manifest_text: str) -> dict[tuple[str, str], list[str]]:
    """Map (normalized name, version) to the sha256 of each wheel for that pin."""
    hashes: dict[tuple[str, str], list[str]] = {}
    for raw in manifest_text.splitlines():
        parts = raw.split()
        if len(parts) != 2:
            continue
        digest, filename = parts[0].lower(), parts[1].lstrip("*")
        if not _SHA256.match(digest) or not filename.endswith(".whl"):
            continue
        fields = filename[: -len(".whl")].split("-")
        if len(fields) < 5:
            continue
        key = (normalize(fields[0]), fields[1])
        hashes.setdefault(key, [])
        if digest not in hashes[key]:
            hashes[key].append(digest)
    return hashes


def extend_requirements(
    requirements_text: str, hashes: dict[tuple[str, str], list[str]]
) -> tuple[str, int]:
    """Return requirements text with wheelhouse hashes added, and the pin count."""
    lines = requirements_text.splitlines()
    out: list[str] = []
    extended = 0
    for index, line in enumerate(lines):
        match = _PIN.match(line)
        if not match:
            out.append(line)
            continue
        key = (normalize(match["name"]), match["version"])
        # A pin's hashes span its line plus the indented continuation lines.
        block = [line]
        for follow in lines[index + 1 :]:
            if not follow.startswith((" ", "\t")):
                break
            block.append(follow)
        existing = set(re.findall(r"sha256:([0-9a-f]{64})", "\n".join(block)))
        extra = [h for h in hashes.get(key, []) if h not in existing]
        if not extra:
            out.append(line)
            continue
        extended += 1
        stripped = line.rstrip()
        continued = stripped.endswith("\\")
        out.append(stripped if continued else stripped + " \\")
        for i, digest in enumerate(extra):
            last = i == len(extra) - 1
            out.append(
                f"    --hash=sha256:{digest}"
                + ("" if last and not continued else " \\")
            )
    trailing = "\n" if requirements_text.endswith("\n") else ""
    return "\n".join(out) + trailing, extended


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print(__doc__.strip().splitlines()[-3], file=sys.stderr)
        return 2
    requirements, manifest, output = (Path(p) for p in argv[1:])
    try:
        text, count = extend_requirements(
            requirements.read_text(encoding="utf-8"),
            manifest_hashes(manifest.read_text(encoding="utf-8")),
        )
        output.write_text(text, encoding="utf-8")
    except OSError as exc:
        print(f"wheelhouse hashes: {exc}", file=sys.stderr)
        return 2
    print(count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
