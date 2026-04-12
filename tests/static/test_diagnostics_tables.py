"""Tests for diagnostics panel formatting in settings page (JTN-646).

System Health and Isolation Summary panels should render as labeled tables,
not raw JSON.stringify output. Extends the JTN-384 pattern.
"""

from pathlib import Path

JS_PATH = Path("src/static/scripts/settings_page.js")


def _read_js():
    return JS_PATH.read_text()


class TestDiagnosticsNoRawJSON:
    """Ensure refreshHealth and refreshIsolation no longer dump raw JSON."""

    def test_no_json_stringify_for_system_health(self):
        js = _read_js()
        assert "JSON.stringify(system," not in js
        assert "JSON.stringify(system, null" not in js

    def test_no_json_stringify_for_plugin_health(self):
        js = _read_js()
        assert "JSON.stringify(plugins.items" not in js

    def test_no_json_stringify_for_isolation(self):
        js = _read_js()
        # Old code did: JSON.stringify(data, null, 2) in refreshIsolation
        # Ensure the isolation panel no longer dumps raw JSON.
        assert "textContent = JSON.stringify(" not in js


class TestDiagnosticsTableBuilders:
    """Ensure helpers for the new tables are defined."""

    def test_build_system_health_table_defined(self):
        js = _read_js()
        assert "function buildSystemHealthTable" in js

    def test_build_isolation_table_defined(self):
        js = _read_js()
        assert "function buildIsolationTable" in js

    def test_build_plugin_health_table_defined(self):
        js = _read_js()
        assert "function buildPluginHealthTable" in js

    def test_system_health_labels(self):
        js = _read_js()
        for label in ("CPU", "Memory", "Disk", "Uptime"):
            assert label in js

    def test_format_uptime_defined(self):
        js = _read_js()
        assert "function formatUptime" in js

    def test_format_percent_defined(self):
        js = _read_js()
        assert "function formatPercent" in js

    def test_empty_isolation_message(self):
        js = _read_js()
        assert "No plugins isolated" in js

    def test_bench_table_class_reused(self):
        """The diagnostics tables should reuse the .bench-table CSS class."""
        js = _read_js()
        # Count occurrences to ensure the class is applied in multiple tables.
        assert js.count('"bench-table"') >= 3
