#!/usr/bin/env python3
"""Per-file and per-package coverage floors for critical modules.

The global floor lives in ``.coveragerc`` (``fail_under``). This gate adds
floors for the modules whose regressions hurt the device most, so a drop in
one of them cannot hide inside a healthy total.

Two profiles, because they read different reports:

* ``full`` (default) - the full-suite ``coverage.xml`` from the CI ``tests``
  job. Floors sit ~1-2 points under the measured numbers so they ratchet
  without flaking.
* ``preflash`` - the 15-file subset run by ``scripts/preflash_validate.sh``
  (``INKYPI_VALIDATE_COVERAGE=1``). That subset only exercises the refresh
  task, the display manager and config, so it keeps its own, lower floors.

A key ending in ``/`` is a package: its lines and branches are summed across
every file under that prefix (subpackages included). Floors are fractions:
``(min_line_rate, min_branch_rate)``.

When a floor fails because coverage genuinely dropped, add tests. When it
fails because you raised coverage, raise the floor to ~1 point under the new
number in the same PR.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import defusedxml.ElementTree as ET

# Measured on main @ 38c08e10 (CI run 42440236419, coverage-3.13 artifact):
# total 91.27%. Small files have coarse granularity (blackout.py has two
# branches, so one missed branch is -50%), hence the looser branch floors.
FULL_THRESHOLDS: dict[str, tuple[float, float]] = {
    # Packages
    "refresh_task/": (0.93, 0.82),  # 94.4 / 83.9
    "display/": (0.93, 0.85),  # 94.2 / 86.5
    "blueprints/": (0.89, 0.83),  # 90.7 / 85.1
    "app_setup/": (0.91, 0.84),  # 92.8 / 85.6
    # Files
    # task.py was split into task.py + mixin modules after the run above.
    # These four were measured by a local run of every refresh-task-related
    # test file (a strict subset of the full suite, so a lower bound on it).
    "refresh_task/task.py": (0.91, 0.85),  # 92.5 / 86.7 (subset)
    "refresh_task/refresh_cycle.py": (0.91, 0.83),  # 92.3 / 84.6 (subset)
    "refresh_task/command_queue.py": (0.91, 0.86),  # 92.5 / 88.1 (subset)
    "refresh_task/loop_scheduling.py": (0.94, 0.90),  # 95.5 / 92.3 (subset)
    "display/display_manager.py": (0.94, 0.89),  # 95.9 / 91.3
    "config.py": (0.88, 0.82),  # 89.8 / 84.4
    "app_setup/auth.py": (0.94, 0.86),  # 95.7 / 88.5
    "app_setup/security_middleware.py": (0.91, 0.83),  # 92.5 / 85.4
    "blueprints/auth.py": (0.89, 0.81),  # 91.5 / 84.4
    "utils/security_utils.py": (0.93, 0.92),  # 95.4 / 96.2
    "utils/boot_self_test.py": (0.92, 0.88),  # 93.4 / 94.4
    "utils/blackout.py": (0.87, 0.50),  # 90.3 / 100 (2 branches)
    "utils/asset_check.py": (0.87, 0.90),  # 88.9 / 92.9
}

# The preflash subset (coverage-gate job artifact, same run):
# display_manager.py 82.6 / 71.7, config.py 73.4 / 65.6. The refresh_task
# entries replace the old single task.py floor (70.5 / 54.7) after task.py was
# split into mixin modules; measured with a local run of the same 14 files.
PREFLASH_THRESHOLDS: dict[str, tuple[float, float]] = {
    "refresh_task/task.py": (0.81, 0.50),  # 83.1 / 53.3
    "refresh_task/refresh_cycle.py": (0.71, 0.50),  # 73.1 / 53.8
    "refresh_task/command_queue.py": (0.60, 0.57),  # 61.9 / 59.5
    "refresh_task/loop_scheduling.py": (0.50, 0.32),  # 52.3 / 34.6
    "display/display_manager.py": (0.80, 0.70),
    "config.py": (0.72, 0.64),
}

PROFILES: dict[str, dict[str, tuple[float, float]]] = {
    "full": FULL_THRESHOLDS,
    "preflash": PREFLASH_THRESHOLDS,
}


@dataclass
class Counts:
    lines_valid: int = 0
    lines_covered: int = 0
    branches_valid: int = 0
    branches_covered: int = 0

    def add(self, other: Counts) -> None:
        self.lines_valid += other.lines_valid
        self.lines_covered += other.lines_covered
        self.branches_valid += other.branches_valid
        self.branches_covered += other.branches_covered

    @property
    def line_rate(self) -> float:
        return self.lines_covered / self.lines_valid if self.lines_valid else 1.0

    @property
    def branch_rate(self) -> float:
        if not self.branches_valid:
            return 1.0
        return self.branches_covered / self.branches_valid


def _parse_condition_coverage(value: str) -> tuple[int, int]:
    """``"50% (1/2)"`` -> ``(1, 2)``."""
    try:
        fraction = value.split("(", 1)[1].rstrip(")")
        covered, total = fraction.split("/", 1)
        return int(covered), int(total)
    except (IndexError, ValueError):
        return 0, 0


def _find_file_counts(coverage_xml: Path) -> dict[str, Counts]:
    root = ET.parse(coverage_xml).getroot()
    counts: dict[str, Counts] = {}
    for class_node in root.findall(".//class"):
        filename = class_node.attrib.get("filename")
        if not filename:
            continue
        file_counts = counts.setdefault(filename, Counts())
        for line in class_node.findall("./lines/line"):
            file_counts.lines_valid += 1
            if int(line.attrib.get("hits", "0")) > 0:
                file_counts.lines_covered += 1
            if line.attrib.get("branch") == "true":
                covered, total = _parse_condition_coverage(
                    line.attrib.get("condition-coverage", "")
                )
                file_counts.branches_covered += covered
                file_counts.branches_valid += total
    return counts


def _resolve(target: str, files: dict[str, Counts]) -> Counts | None:
    if not target.endswith("/"):
        return files.get(target)
    matched = [c for name, c in files.items() if name.startswith(target)]
    if not matched:
        return None
    total = Counts()
    for item in matched:
        total.add(item)
    return total


def check(
    coverage_xml: Path, thresholds: dict[str, tuple[float, float]]
) -> tuple[list[str], list[str]]:
    """Return ``(failures, report_lines)`` for *thresholds* against the XML."""
    files = _find_file_counts(coverage_xml)
    failures: list[str] = []
    report: list[str] = []
    for target, (min_line, min_branch) in thresholds.items():
        actual = _resolve(target, files)
        if actual is None:
            failures.append(f"{target}: missing from coverage report")
            continue
        report.append(
            f"{target}: line={actual.line_rate:.1%} (floor {min_line:.0%}) "
            f"branch={actual.branch_rate:.1%} (floor {min_branch:.0%})"
        )
        if actual.line_rate < min_line:
            failures.append(
                f"{target}: line-rate {actual.line_rate:.1%} < required {min_line:.1%}"
            )
        if actual.branch_rate < min_branch:
            failures.append(
                f"{target}: branch-rate {actual.branch_rate:.1%} "
                f"< required {min_branch:.1%}"
            )
    return failures, report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gate critical module coverage.")
    parser.add_argument("coverage_xml", help="Path to coverage.xml")
    parser.add_argument(
        "--profile",
        choices=sorted(PROFILES),
        default="full",
        help="Which floor table to apply (default: full-suite floors).",
    )
    args = parser.parse_args(argv)

    coverage_xml = Path(args.coverage_xml)
    if not coverage_xml.is_file():
        raise SystemExit(f"coverage xml not found: {coverage_xml}")

    failures, report = check(coverage_xml, PROFILES[args.profile])
    for line in report:
        print(line)
    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
