"""Tests for benchmark display formatting in settings page (JTN-384).

Benchmarks should render as a labeled table, not raw JSON.stringify output.
Null values should display as an em-dash, not the literal string 'null'.
"""

from pathlib import Path

JS_PATH = Path("src/static/scripts/settings/diagnostics.js")


def _read_js():
    return JS_PATH.read_text()


class TestBenchmarkNoRawJSON:
    """Ensure refreshBenchmarks no longer dumps raw JSON to the UI."""

    def test_no_json_stringify_for_summary(self):
        """Summary data must not be rendered via JSON.stringify."""
        js = _read_js()
        # The old code did: JSON.stringify(summary.summary || {}, null, 2)
        assert "JSON.stringify(summary.summary" not in js

    def test_no_json_stringify_for_plugins(self):
        """Plugin data must not be rendered via JSON.stringify."""
        js = _read_js()
        # The old code did: JSON.stringify((plugins.items || []).slice(0, 10), null, 2)
        assert "JSON.stringify((plugins.items" not in js


class TestBenchmarkTableBuilder:
    """Ensure the JS defines proper table-building helpers."""

    def test_build_summary_table_defined(self):
        js = _read_js()
        assert "function buildSummaryTable" in js

    def test_build_plugins_table_defined(self):
        js = _read_js()
        assert "function buildPluginsTable" in js

    def test_build_refreshes_table_defined(self):
        js = _read_js()
        assert "function buildRefreshesTable" in js

    def test_build_stages_table_defined(self):
        js = _read_js()
        assert "function buildStagesTable" in js

    def test_benchmark_refreshes_ignore_stale_responses(self):
        js = _read_js()
        assert "benchmarkRequestSeq" in js
        assert "windowValue !== getBenchmarkWindow()" in js

    def test_benchmark_errors_check_response_status(self):
        js = _read_js()
        assert "!resp.ok || body?.success === false" in js
        assert "!resp.ok || data?.success === false" in js

    def test_stage_panel_reset_helper_defined(self):
        js = _read_js()
        assert "function resetStagesPanel" in js
        assert "No refreshes available for this window." in js

    def test_stage_labels_defined(self):
        """Human-readable labels must replace raw keys like 'generate_ms'."""
        js = _read_js()
        for label in ("Request", "Generate", "Preprocess", "Display"):
            assert label in js

    def test_null_rendered_as_em_dash(self):
        """formatMs must return an em-dash for null/undefined values."""
        js = _read_js()
        # U+2014 em-dash or its JS unicode escape
        assert "\\u2014" in js or "\u2014" in js


class TestBenchmarkTableCSS:
    """Ensure the bench-table CSS class exists."""

    def test_bench_table_class_in_css(self):
        css = Path("src/static/styles/partials/_settings-console.css").read_text()
        assert ".bench-table" in css

    def test_bench_table_class_used_in_js(self):
        js = _read_js()
        assert '"bench-table"' in js

    def test_benchmark_window_control_exists(self):
        html = Path("src/templates/settings.html").read_text()
        assert 'id="benchmarkWindow"' in html
        assert 'id="benchRefreshes"' in html
        assert 'id="benchStages"' in html
