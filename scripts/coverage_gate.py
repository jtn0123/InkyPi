#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

THRESHOLDS: dict[str, tuple[float, float]] = {
    "refresh_task.py": (0.65, 0.50),
    "display/display_manager.py": (0.75, 0.65),
    "config.py": (0.72, 0.58),
}


def _find_class_metrics(coverage_xml: Path) -> dict[str, tuple[float, float]]:
    root = ET.parse(coverage_xml).getroot()
    metrics: dict[str, tuple[float, float]] = {}
    for class_node in root.findall(".//class"):
        filename = class_node.attrib.get("filename")
        if not filename:
            continue
        line_rate = float(class_node.attrib.get("line-rate", "0"))
        branch_rate = float(class_node.attrib.get("branch-rate", "0"))
        metrics[filename] = (line_rate, branch_rate)
    return metrics


def main() -> int:
    parser = argparse.ArgumentParser(description="Gate critical file coverage.")
    parser.add_argument("coverage_xml", help="Path to coverage.xml")
    args = parser.parse_args()

    coverage_xml = Path(args.coverage_xml)
    if not coverage_xml.is_file():
        raise SystemExit(f"coverage xml not found: {coverage_xml}")

    metrics = _find_class_metrics(coverage_xml)
    failures: list[str] = []
    for filename, (min_line, min_branch) in THRESHOLDS.items():
        actual = metrics.get(filename)
        if actual is None:
            failures.append(f"{filename}: missing from coverage report")
            continue
        line_rate, branch_rate = actual
        if line_rate < min_line:
            failures.append(
                f"{filename}: line-rate {line_rate:.1%} < required {min_line:.1%}"
            )
        if branch_rate < min_branch:
            failures.append(
                f"{filename}: branch-rate {branch_rate:.1%} < required {min_branch:.1%}"
            )

    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1

    for filename, (line_rate, branch_rate) in sorted(metrics.items()):
        if filename in THRESHOLDS:
            print(f"{filename}: line={line_rate:.1%} branch={branch_rate:.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
