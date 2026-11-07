"""The relative benchmark gate only enforces timings measured on the same CPU."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "benchmark_compare.py"


def _write(
    path: Path, medians: dict[str, float], cpu: str | None = "Intel Xeon"
) -> Path:
    data: dict[str, object] = {
        "benchmarks": [{"name": n, "stats": {"median": m}} for n, m in medians.items()]
    }
    if cpu is not None:
        data["machine_info"] = {"cpu": {"brand_raw": cpu}}
    path.write_text(json.dumps(data))
    return path


def _run(baseline: Path, current: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--baseline",
            str(baseline),
            "--current",
            str(current),
            "--threshold",
            "15",
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_same_cpu_regression_fails(tmp_path: Path) -> None:
    base = _write(tmp_path / "b.json", {"a": 1.0})
    cur = _write(tmp_path / "c.json", {"a": 1.5})
    result = _run(base, cur)
    assert result.returncode == 1
    assert "FAILED" in result.stdout


def test_same_cpu_within_threshold_passes(tmp_path: Path) -> None:
    base = _write(tmp_path / "b.json", {"a": 1.0})
    cur = _write(tmp_path / "c.json", {"a": 1.1})
    assert _run(base, cur).returncode == 0


def test_different_cpu_reports_but_does_not_fail(tmp_path: Path) -> None:
    base = _write(tmp_path / "b.json", {"a": 1.0}, cpu="Intel(R) Xeon(R) 6975P-C")
    cur = _write(tmp_path / "c.json", {"a": 2.0}, cpu="AMD EPYC 7763 64-Core Processor")
    result = _run(base, cur)
    assert result.returncode == 0, result.stdout
    assert "FAIL  a" in result.stdout  # still visible in the log
    assert "SKIPPED: relative regression check" in result.stdout


def test_different_cpu_still_fails_on_missing_benchmark(tmp_path: Path) -> None:
    base = _write(tmp_path / "b.json", {"a": 1.0, "b": 1.0}, cpu="Intel")
    cur = _write(tmp_path / "c.json", {"a": 1.0}, cpu="AMD")
    result = _run(base, cur)
    assert result.returncode == 1
    assert "missing from the current run" in result.stdout


def test_unknown_cpu_is_still_enforced(tmp_path: Path) -> None:
    # The committed fallback baseline may lack machine_info; keep it blocking.
    base = _write(tmp_path / "b.json", {"a": 1.0}, cpu=None)
    cur = _write(tmp_path / "c.json", {"a": 2.0}, cpu="AMD")
    assert _run(base, cur).returncode == 1
