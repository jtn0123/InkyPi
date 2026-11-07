#!/usr/bin/env python3
"""Compare pytest-benchmark JSON output against a stored baseline.

Exit 0 if all benchmarks are within the allowed regression threshold.
Exit 1 if any benchmark regressed beyond the threshold.

Timings are only comparable on the same CPU. GitHub's hosted runners mix
Intel Xeon and several AMD EPYC models, and a cached baseline from one model
made unrelated PRs fail by 40-140% on another. When both files record a CPU
model and they differ, the timing comparison is reported but not enforced
(a benchmark missing from the current run still fails); the absolute budgets
in ``scripts/perf_budget_gate.py`` keep guarding real regressions.

Usage:
    python scripts/benchmark_compare.py \
        --baseline tests/benchmarks/baseline.json \
        --current  /tmp/bench-current.json \
        [--threshold 15]

The threshold is a percentage (default 15, i.e. +15% regression).
It can also be set via the BENCHMARK_THRESHOLD_PCT environment variable.
"""

from __future__ import annotations

import argparse
import json
import os
import sys


def load_benchmarks(path: str) -> dict[str, float]:
    """Return {test_name: median_seconds} from a pytest-benchmark JSON file."""
    with open(path) as f:
        data = json.load(f)
    return {b["name"]: b["stats"]["median"] for b in data["benchmarks"]}


def cpu_model(path: str) -> str | None:
    """Return the CPU model pytest-benchmark recorded, if any."""
    with open(path) as f:
        data = json.load(f)
    cpu = data.get("machine_info", {}).get("cpu", {})
    model = cpu.get("brand_raw") if isinstance(cpu, dict) else None
    return model.strip() if isinstance(model, str) and model.strip() else None


def compare(
    baseline: dict[str, float],
    current: dict[str, float],
    threshold_pct: float,
) -> list[str]:
    """Return a list of failure messages for benchmarks that regressed."""
    failures: list[str] = []
    for name, base_val in sorted(baseline.items()):
        cur_val = current.get(name)
        if cur_val is None:
            label = f"  FAIL  {name}: missing in current run (present in baseline)"
            print(label)
            failures.append(label)
            continue
        if base_val == 0:
            continue
        change_pct = ((cur_val - base_val) / base_val) * 100
        status = "PASS" if change_pct <= threshold_pct else "FAIL"
        label = f"  {status}  {name}: {base_val*1e6:.1f}us -> {cur_val*1e6:.1f}us ({change_pct:+.1f}%)"
        print(label)
        if status == "FAIL":
            failures.append(label)

    # Check for new benchmarks (informational only, not a failure)
    new_benchmarks = set(current) - set(baseline)
    for name in sorted(new_benchmarks):
        print(f"  NEW   {name}: {current[name]*1e6:.1f}us (no baseline)")

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline",
        default="tests/benchmarks/baseline.json",
        help="Path to the stored baseline JSON (default: tests/benchmarks/baseline.json)",
    )
    parser.add_argument(
        "--current",
        required=True,
        help="Path to the current benchmark JSON output",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="Regression threshold percentage (default: 15, or BENCHMARK_THRESHOLD_PCT env var)",
    )
    args = parser.parse_args()

    threshold = args.threshold
    if threshold is None:
        threshold = float(os.environ.get("BENCHMARK_THRESHOLD_PCT", "15"))

    print(f"Benchmark regression gate (threshold: +{threshold:.0f}%)")
    print(f"  Baseline: {args.baseline}")
    print(f"  Current:  {args.current}")
    print()

    baseline = load_benchmarks(args.baseline)
    current = load_benchmarks(args.current)

    if not baseline:
        print("ERROR: No benchmarks found in baseline file")
        return 1

    failures = compare(baseline, current, threshold)

    base_cpu, cur_cpu = cpu_model(args.baseline), cpu_model(args.current)
    if base_cpu and cur_cpu and base_cpu != cur_cpu:
        missing = [f for f in failures if "missing in current run" in f]
        print()
        print(f"NOTE: runner CPU differs from the baseline ({base_cpu} -> {cur_cpu});")
        print("      timings are not comparable, so regressions are not enforced.")
        if missing:
            print(f"FAILED: {len(missing)} benchmark(s) missing from the current run")
            return 1
        print("SKIPPED: relative regression check (different CPU)")
        return 0

    print()
    if failures:
        print(
            f"FAILED: {len(failures)} benchmark(s) exceeded +{threshold:.0f}% regression threshold"
        )
        return 1

    print(f"PASSED: All benchmarks within +{threshold:.0f}% threshold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
