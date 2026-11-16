#!/usr/bin/env python3
"""Compare a mypy run with its checked-in baseline of error fingerprints.

    python scripts/mypy_ratchet.py tests scripts/mypy_tests_baseline.txt
    python scripts/mypy_ratchet.py tests scripts/mypy_tests_baseline.txt --update

A fingerprint is ``path:error-code``, and the baseline lists each one with the
number of errors mypy reports for it. A single total let a fixed error in one
file pay for a new one in another; per-fingerprint counts don't. Any
fingerprint that is new, has more or fewer errors than listed, or has gone
fails the check, and only those differences are printed.

After fixing errors, ``--update`` rewrites the list (the comment header at the
top is kept), so the improvement becomes the new floor. scripts/lint.sh runs
this for src/, tests/ and scripts/; see docs/typing.md.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import textwrap
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class RatchetError(Exception):
    """mypy produced no usable result, or a baseline file is malformed."""


@dataclass(frozen=True)
class MypyError:
    """One error from mypy's JSON output."""

    file: str
    line: int
    column: int
    code: str
    message: str
    hint: str = ""

    @property
    def fingerprint(self) -> str:
        return f"{self.file}:{self.code}"

    def __str__(self) -> str:
        text = f"{self.file}:{self.line}:{self.column}: {self.message}  [{self.code}]"
        if self.hint:
            text += "\n" + textwrap.indent(self.hint, "    ")
        return text


@dataclass(frozen=True)
class Baseline:
    """A baseline file: its comment header and the fingerprint counts."""

    header: list[str]
    counts: Counter[str]


def _relative(path: str) -> str:
    candidate = Path(path)
    if candidate.is_absolute():
        try:
            candidate = candidate.relative_to(ROOT)
        except ValueError:
            pass
    return candidate.as_posix()


def parse_mypy_output(stdout: str) -> list[MypyError]:
    """The errors in ``mypy -O json`` output; notes are left out."""
    errors = []
    for raw in stdout.splitlines():
        if not raw.strip():
            continue
        try:
            record = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RatchetError(f"mypy printed a line that isn't JSON: {raw}") from exc
        if not isinstance(record, dict):
            raise RatchetError(f"mypy printed an unexpected JSON value: {raw}")
        if record.get("severity") != "error":
            continue
        errors.append(
            MypyError(
                file=_relative(str(record["file"])),
                line=int(record["line"]),
                column=int(record["column"]),
                # Every error mypy reports has a code; guard the format anyway.
                code=str(record.get("code") or "no-code"),
                message=str(record["message"]),
                hint=str(record.get("hint") or ""),
            )
        )
    return errors


def run_mypy(target: str) -> list[MypyError]:
    """Run mypy (strict, from mypy.ini) on *target* and return its errors."""
    result = subprocess.run(
        [sys.executable, "-m", "mypy", "-O", "json", target],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    # 0: clean, 1: errors found. Anything else (2) is a crash, a config error
    # or a module that couldn't be read, and has no result to compare.
    if result.returncode not in (0, 1):
        raise RatchetError(
            f"mypy {target} failed (exit {result.returncode}):\n"
            f"{result.stdout}{result.stderr}"
        )
    errors = parse_mypy_output(result.stdout)
    if result.returncode == 1 and not errors:
        raise RatchetError(
            f"mypy {target} exited 1 without reporting an error:\n"
            f"{result.stdout}{result.stderr}"
        )
    return errors


def parse_baseline(text: str, source: str) -> Baseline:
    """Read a baseline: comments, then one ``path:error-code count`` per line."""
    header: list[str] = []
    counts: Counter[str] = Counter()
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            if not counts:
                header.append(line)
            elif stripped:
                raise RatchetError(
                    f"{source}:{number}: comments go in the header above the "
                    "fingerprints (--update rewrites the list below it)"
                )
            continue
        fingerprint, _, count = stripped.rpartition(" ")
        if ":" not in fingerprint or not count.isdigit() or int(count) == 0:
            raise RatchetError(
                f"{source}:{number}: expected 'path:error-code count', got {line!r}"
            )
        if fingerprint in counts:
            raise RatchetError(f"{source}:{number}: {fingerprint} is listed twice")
        counts[fingerprint] = int(count)
    return Baseline(header, counts)


def render_baseline(header: Sequence[str], counts: Counter[str]) -> str:
    """The baseline file for *counts*, sorted, under *header*."""
    lines = list(header)
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and counts:
        lines.append("")
    lines += [f"{fingerprint} {counts[fingerprint]}" for fingerprint in sorted(counts)]
    return "\n".join(lines) + "\n"


def compare(
    baseline: Counter[str], current: Counter[str]
) -> tuple[dict[str, tuple[int, int]], dict[str, tuple[int, int]]]:
    """Fingerprints with more errors than the baseline, and with fewer.

    Each maps to (baseline count, current count); a new fingerprint has a
    baseline count of 0, a vanished one a current count of 0.
    """
    worse: dict[str, tuple[int, int]] = {}
    better: dict[str, tuple[int, int]] = {}
    for fingerprint in sorted(baseline.keys() | current.keys()):
        was, now = baseline[fingerprint], current[fingerprint]
        if now > was:
            worse[fingerprint] = (was, now)
        elif now < was:
            better[fingerprint] = (was, now)
    return worse, better


def _display(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def main(
    argv: Sequence[str] | None = None,
    run: Callable[[str], list[MypyError]] = run_mypy,
) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("target", help="directory to check, e.g. tests")
    parser.add_argument("baseline", type=Path, help="its baseline file")
    parser.add_argument(
        "--update",
        action="store_true",
        help="rewrite the baseline from this run instead of comparing",
    )
    args = parser.parse_args(argv)
    target: str = args.target
    baseline_path: Path = args.baseline
    label = target.rstrip("/") + "/"
    shown = _display(baseline_path)

    try:
        baseline = parse_baseline(baseline_path.read_text(encoding="utf-8"), shown)
        errors = run(target)
    except (OSError, RatchetError) as exc:
        print(f"❌ mypy {label}: {exc}")
        return 1
    current = Counter(error.fingerprint for error in errors)

    if args.update:
        baseline_path.write_text(
            render_baseline(baseline.header, current), encoding="utf-8"
        )
        print(
            f"Wrote {len(current)} fingerprint(s) ({sum(current.values())} "
            f"error(s)) to {shown}."
        )
        return 0

    worse, better = compare(baseline.counts, current)
    if not worse and not better:
        total = sum(current.values())
        if total:
            print(
                f"✅ mypy {label}: {total} error(s) in {len(current)} "
                f"fingerprint(s), as listed in {shown}"
            )
        else:
            print(f"✅ mypy {label}: clean")
        return 0

    if worse:
        print(f"❌ mypy {label}: errors beyond {shown}:")
        for fingerprint, (was, now) in worse.items():
            print(f"  {fingerprint}: {now} error(s), baseline {was}")
            for error in errors:
                if error.fingerprint == fingerprint:
                    print(textwrap.indent(str(error), "      "))
    if better:
        print(f"❌ mypy {label}: fixed errors still listed in {shown}:")
        for fingerprint, (was, now) in better.items():
            print(f"  {fingerprint}: {now} error(s), baseline {was}")
        print(
            "  Lock in the improvement: "
            f"python scripts/mypy_ratchet.py {target} {shown} --update"
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
