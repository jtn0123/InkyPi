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
import traceback
from pathlib import Path


def _parse_env_float(name: str, fallback: float) -> float:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return fallback
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        print(
            f"warning: ignoring malformed {name}={raw_value!r}; using {fallback}",
            file=sys.stderr,
        )
        return fallback


def _parse_env_int(name: str, fallback: int) -> int:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return fallback
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        print(
            f"warning: ignoring malformed {name}={raw_value!r}; using {fallback}",
            file=sys.stderr,
        )
        return fallback


def _load_benchmarks(path: str) -> list[dict]:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
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
        if group == "plugin_render":
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
    preflash_script = repo_root / "scripts" / "preflash_smoke.py"
    cmd = [sys.executable, str(preflash_script), "app"]
    runs: list[float] = []
    sample_failures: list[str] = []
    for idx in range(samples):
        start = time.perf_counter()
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            elapsed = time.perf_counter() - start
            sample_failures.append(
                f"sample {idx + 1} timed out after {timeout_s:.1f}s (elapsed {elapsed:.3f}s)"
            )
            continue
        elapsed = time.perf_counter() - start
        if proc.returncode != 0:
            stdout = (proc.stdout or "").strip()
            stderr = (proc.stderr or "").strip()
            sample_failures.append(
                f"cold-start probe failed on sample {idx + 1} (exit {proc.returncode})\n"
                f"stdout:\n{stdout}\n\nstderr:\n{stderr}"
            )
            continue
        runs.append(elapsed)
    for failure in sample_failures:
        print(f"cold-start warning: {failure}", file=sys.stderr)
    if not runs:
        raise RuntimeError(
            "all cold-start samples failed:\n" + "\n".join(sample_failures)
        )
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
    plugin_render_default = _parse_env_float("PERF_PLUGIN_RENDER_BUDGET_MS", 2000.0)
    cold_start_default = _parse_env_float("PERF_COLD_START_BUDGET_S", 3.0)
    cold_start_samples_default = _parse_env_int("PERF_COLD_START_SAMPLES", 3)
    cold_start_timeout_default = _parse_env_float("PERF_COLD_START_TIMEOUT_S", 90.0)

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bench-json",
        required=True,
        help="Path to pytest-benchmark JSON output",
    )
    parser.add_argument(
        "--plugin-render-max-ms",
        type=float,
        default=plugin_render_default,
        help="Max allowed median for plugin render benchmarks (ms)",
    )
    parser.add_argument(
        "--cold-start-max-s",
        type=float,
        default=cold_start_default,
        help="Max allowed median cold-start time (seconds)",
    )
    parser.add_argument(
        "--cold-start-samples",
        type=int,
        default=cold_start_samples_default,
        help="Number of cold-start probe samples",
    )
    parser.add_argument(
        "--cold-start-timeout-s",
        type=float,
        default=cold_start_timeout_default,
        help="Timeout per cold-start probe (seconds)",
    )
    args = parser.parse_args()

    failures: list[str] = []

    benchmarks = _load_benchmarks(args.bench_json)
    failures.extend(
        evaluate_plugin_render_budget(benchmarks, args.plugin_render_max_ms)
    )

    try:
        cold_runs = run_cold_start_samples(
            max(1, args.cold_start_samples),
            max(1.0, args.cold_start_timeout_s),
        )
    except Exception as exc:
        failures.append(
            "probe=cold_start phase=sampling "
            f"message={exc} traceback={traceback.format_exc(limit=1).strip()}"
        )
    else:
        try:
            failures.extend(
                evaluate_cold_start_budget(cold_runs, args.cold_start_max_s)
            )
        except Exception as exc:
            failures.append(
                "probe=cold_start phase=evaluation "
                f"message={exc} traceback={traceback.format_exc(limit=1).strip()}"
            )

    if failures:
        print("\nFAILED performance budget gate:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("\nPASSED performance budget gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
