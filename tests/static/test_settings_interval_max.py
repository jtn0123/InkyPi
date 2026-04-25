"""Regression guard: plugin-cycle interval must have a unit-aware client max
(ISSUE-009).

Without `max`, users could type 999999 hours, click Save, and only then learn
the server's "less than 24 hours" cap when the request returned 422. The fix
sets `max` dynamically on the `#interval` input based on which `#unit` is
selected (23 for hours, 1439 for minutes).
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FORM_JS = ROOT / "src" / "static" / "scripts" / "settings" / "form.js"


def _read() -> str:
    return FORM_JS.read_text(encoding="utf-8")


def test_form_js_caps_interval_max_per_unit():
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
    # Hours: 23 (server allows < 24 hours). Minutes: 1439 (= 23h59).
    # Match the actual return statements rather than a bare `" 23"` /
    # `"1439"` substring, because comments inside the helper happen to
    # mention "23h59" / "1439" — a regression that dropped the literal
    # `return 23;` would otherwise still pass on comment text alone.
    assert re.search(
        r"return\s+23\b", body
    ), "hour branch must `return 23` (server cap is < 24 hours)"
    assert re.search(
        r"return\s+1439\b", body
    ), "minute branch must `return 1439` (server cap is < 24h = 1440 min)"


def test_unit_change_listener_refreshes_max():
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


def test_populate_interval_fields_sets_initial_max():
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
