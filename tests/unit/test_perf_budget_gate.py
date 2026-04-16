from __future__ import annotations

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


def test_cold_start_budget_uses_median():
    failures = gate.evaluate_cold_start_budget([2.9, 3.1, 2.8], max_median_s=3.0)
    assert failures == []


def test_cold_start_budget_fails_when_median_exceeds():
    failures = gate.evaluate_cold_start_budget([3.1, 3.2, 3.0], max_median_s=3.0)
    assert failures
    assert "exceeds budget" in failures[0]
