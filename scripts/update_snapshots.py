#!/usr/bin/env python3
"""Regenerate golden-file baselines for plugin snapshot tests.

Run from the project root:

    python scripts/update_snapshots.py

The script re-executes snapshot tests with ``--update-snapshots`` so every
assert_image_snapshot() call writes fresh baseline PNGs instead of comparing.

Pass --yes / -y to skip the confirmation prompt (e.g. in CI pipelines where
intentional regeneration is desired):

    python scripts/update_snapshots.py --yes
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip the confirmation prompt.",
    )
    args = parser.parse_args()

    if not args.yes:
        print(
            "This will overwrite ALL stored snapshot baselines.\n"
            "Only run this when the visual output changes are intentional.\n"
        )
        answer = input("Proceed? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Aborted.")
            return 1

    env = {**os.environ}

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "tests/snapshots/",
        "-v",
        "--no-header",
        "--tb=short",
        "--update-snapshots",
    ]

    print("Running:", " ".join(cmd))
    result = subprocess.run(cmd, env=env)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
