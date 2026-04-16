#!/usr/bin/env python3
"""Performance budget gate for CI.

JTN-738 contract:
* plugin-render medians must stay under a fixed ceiling
* cold-start median must stay under a fixed ceiling
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path


def _load_benchmarks(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    rows = data.get("benchmarks", [])
    if not isinstance(rows, list):
        return []
    return [r for r in rows if isinstance(r, dict)]


def _plugin_render_rows(benchmarks: list[dict]) -> list[tuple[str, float]]:
    rows: list[tuple[str, float]] = []
    for bench in benchmarks:
        name = str(bench.get("name", ""))
        group = bench.get("group")
        stats = bench.get("stats", {})
        if not isinstance(stats, dict):
            continue
        median_s = stats.get("median")
        if not isinstance(median_s, (int, float)):
            continue
        if group == "plugin_render" or name.startswith("test_bench_"):
            rows.append((name, float(median_s) * 1000.0))
    return rows


def evaluate_plugin_render_budget(
    benchmarks: list[dict], max_median_ms: float
) -> list[str]:
    failures: list[str] = []
    rows = _plugin_render_rows(benchmarks)
    if not rows:
        return ["No plugin-render benchmarks found in benchmark JSON"]

    for name, median_ms in rows:
        print(
            f"plugin-render: {name} median={median_ms:.2f}ms (budget {max_median_ms:.2f}ms)"
        )
        if median_ms > max_median_ms:
            failures.append(
                f"{name} median {median_ms:.2f}ms exceeds plugin-render budget {max_median_ms:.2f}ms"
            )
    return failures


def run_cold_start_samples(samples: int, timeout_s: float) -> list[float]:
    """Measure cold-start wall clock by running preflash app smoke in subprocesses."""
    repo_root = Path(__file__).resolve().parents[1]
    cmd = [sys.executable, "scripts/preflash_smoke.py", "app"]
    runs: list[float] = []
    for idx in range(samples):
        start = time.perf_counter()
        proc = subprocess.run(
            cmd,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        elapsed = time.perf_counter() - start
        if proc.returncode != 0:
            stdout = (proc.stdout or "").strip()
            stderr = (proc.stderr or "").strip()
            raise RuntimeError(
                f"cold-start probe failed on sample {idx + 1} (exit {proc.returncode})\n"
                f"stdout:\n{stdout}\n\nstderr:\n{stderr}"
            )
        runs.append(elapsed)
    return runs


def evaluate_cold_start_budget(runs_s: list[float], max_median_s: float) -> list[str]:
    if not runs_s:
        return ["No cold-start samples collected"]
    for idx, val in enumerate(runs_s, start=1):
        print(f"cold-start sample {idx}: {val:.3f}s")
    median_s = statistics.median(runs_s)
    print(f"cold-start median: {median_s:.3f}s (budget {max_median_s:.3f}s)")
    if median_s > max_median_s:
        return [f"cold-start median {median_s:.3f}s exceeds budget {max_median_s:.3f}s"]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bench-json",
        required=True,
        help="Path to pytest-benchmark JSON output",
    )
    parser.add_argument(
        "--plugin-render-max-ms",
        type=float,
        default=float(os.environ.get("PERF_PLUGIN_RENDER_BUDGET_MS", "2000")),
        help="Max allowed median for plugin render benchmarks (ms)",
    )
    parser.add_argument(
        "--cold-start-max-s",
        type=float,
        default=float(os.environ.get("PERF_COLD_START_BUDGET_S", "3")),
        help="Max allowed median cold-start time (seconds)",
    )
    parser.add_argument(
        "--cold-start-samples",
        type=int,
        default=int(os.environ.get("PERF_COLD_START_SAMPLES", "3")),
        help="Number of cold-start probe samples",
    )
    parser.add_argument(
        "--cold-start-timeout-s",
        type=float,
        default=float(os.environ.get("PERF_COLD_START_TIMEOUT_S", "90")),
        help="Timeout per cold-start probe (seconds)",
    )
    args = parser.parse_args()

    failures: list[str] = []

    benchmarks = _load_benchmarks(args.bench_json)
    failures.extend(
        evaluate_plugin_render_budget(benchmarks, args.plugin_render_max_ms)
    )

    cold_runs = run_cold_start_samples(
        max(1, args.cold_start_samples),
        max(1.0, args.cold_start_timeout_s),
    )
    failures.extend(evaluate_cold_start_budget(cold_runs, args.cold_start_max_s))

    if failures:
        print("\nFAILED performance budget gate:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("\nPASSED performance budget gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
