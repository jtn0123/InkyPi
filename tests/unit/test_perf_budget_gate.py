from __future__ import annotations

import json

from scripts import perf_budget_gate as gate


def test_plugin_render_budget_passes_under_threshold():
    benches = [
        {
            "name": "test_bench_clock_render",
            "group": "plugin_render",
            "stats": {"median": 0.5},  # 500ms
        }
    ]
    failures = gate.evaluate_plugin_render_budget(benches, max_median_ms=2000)
    assert failures == []


def test_plugin_render_budget_fails_over_threshold():
    benches = [
        {
            "name": "test_bench_clock_render",
            "group": "plugin_render",
            "stats": {"median": 2.5},  # 2500ms
        }
    ]
    failures = gate.evaluate_plugin_render_budget(benches, max_median_ms=2000)
    assert failures
    assert "exceeds plugin-render budget" in failures[0]


def test_plugin_render_budget_ignores_non_plugin_render_group():
    benches = [
        {
            "name": "test_bench_non_plugin_row",
            "group": "cache",
            "stats": {"median": 2.5},  # should be ignored
        },
        {
            "name": "test_bench_clock_render",
            "group": "plugin_render",
            "stats": {"median": 0.5},  # 500ms
        },
    ]
    failures = gate.evaluate_plugin_render_budget(benches, max_median_ms=2000)
    assert failures == []


def test_load_benchmarks_returns_empty_for_missing_file(tmp_path):
    missing = tmp_path / "missing-benchmarks.json"
    assert gate._load_benchmarks(str(missing)) == []


def test_load_benchmarks_returns_empty_for_invalid_json(tmp_path):
    invalid = tmp_path / "invalid-benchmarks.json"
    invalid.write_text("{not-json", encoding="utf-8")
    assert gate._load_benchmarks(str(invalid)) == []


def test_load_benchmarks_filters_non_mapping_rows(tmp_path):
    bench_file = tmp_path / "benchmarks.json"
    bench_file.write_text(
        json.dumps({"benchmarks": [{"name": "ok"}, "bad-row", 123]}),
        encoding="utf-8",
    )
    assert gate._load_benchmarks(str(bench_file)) == [{"name": "ok"}]


def test_cold_start_budget_uses_median():
    failures = gate.evaluate_cold_start_budget([2.9, 3.1, 2.8], max_median_s=3.0)
    assert failures == []


def test_cold_start_budget_fails_when_median_exceeds():
    failures = gate.evaluate_cold_start_budget([3.1, 3.2, 3.0], max_median_s=3.0)
    assert failures
    assert "exceeds budget" in failures[0]
