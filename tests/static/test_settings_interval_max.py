"""Regression guard: plugin-cycle interval must have a unit-aware client max
(ISSUE-009).

Without `max`, users could type 999999 hours, click Save, and only then learn
the server's cap when the request returned 422. The fix sets `max`
dynamically on the `#interval` input based on which `#unit` is selected. The
cap itself is the config schema's maximum for plugin_cycle_interval_seconds,
which the page passes in as ``pluginCycleIntervalMaxSeconds`` (checked in
tests/unit/test_settings_schema_rules.py).
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FORM_JS = ROOT / "src" / "static" / "scripts" / "settings" / "form.js"


def _read() -> str:
    return FORM_JS.read_text(encoding="utf-8")


def test_form_js_caps_interval_max_per_unit() -> None:
    """The form module must compute a unit-specific max and apply it on
    page load + on unit change. Otherwise the field has no max and the
    server has to backstop typos."""
    js = _read()
    assert (
        "_maxIntervalForUnit" in js
    ), "missing _maxIntervalForUnit() helper that maps unit -> interval cap"
    # The two unit values are "hour" and "minute" — the helper must map both.
    fn_match = re.search(
        r"function _maxIntervalForUnit\([^)]*\)\s*\{(?P<body>.*?)\n {4}\}",
        js,
        flags=re.S,
    )
    assert fn_match, "helper body not found"
    body = fn_match.group("body")
    assert '"hour"' in body, "must distinguish hours specifically"
    # The cap comes from the page's boot config (the schema's maximum), not a
    # literal in the script, so the form cannot drift from the saver again.
    assert (
        "config.pluginCycleIntervalMaxSeconds" in body
    ), "the cap must come from the schema maximum the page passes in"
    assert not re.search(
        r"return\s+\d+\s*;", body
    ), "no hard-coded cap: derive it from pluginCycleIntervalMaxSeconds"


def test_unit_change_listener_refreshes_max() -> None:
    """The unit <select> must trigger refreshIntervalMax on change so the
    cap reflects whichever unit the user just picked."""
    js = _read()
    assert "refreshIntervalMax" in js
    # Match the bind() listener: unit -> refreshIntervalMax
    bind_match = re.search(
        r'getElementById\("unit"\)\s*\?\.addEventListener\("change",\s*refreshIntervalMax\)',
        js,
    )
    assert (
        bind_match
    ), "unit <select> must listen for change and call refreshIntervalMax"


def test_populate_interval_fields_sets_initial_max() -> None:
    """First paint must already have the max set so the user sees the cap
    immediately, not only after they wiggle the unit."""
    js = _read()
    populate_match = re.search(
        r"function populateIntervalFields\(\)\s*\{(?P<body>.*?)\n {4}\}",
        js,
        flags=re.S,
    )
    assert populate_match
    assert "refreshIntervalMax()" in populate_match.group("body"), (
        "populateIntervalFields should call refreshIntervalMax after setting "
        "the value/unit so the cap is in place on initial render."
    )
