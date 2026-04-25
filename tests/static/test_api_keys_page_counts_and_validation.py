"""Regression guards for the API Keys page (`/api-keys`, generic mode).

Covers three related dogfood findings:
  - ISSUE-003: the "X providers / Y configured" badges did not update when
    the user added a preset row, even though the editor row was visible.
  - ISSUE-004: the badges always rendered identical numbers (because both
    were derived from `entries|length` server-side), so the pair was
    redundant.
  - ISSUE-005: clicking Save with an empty new-row value showed only a
    corner toast and never set `aria-invalid` / inline error on the
    offending input.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API_KEYS_JS = ROOT / "src" / "static" / "scripts" / "api_keys_page.js"


def _read_js() -> str:
    return API_KEYS_JS.read_text(encoding="utf-8")


def test_refresh_key_counts_function_exists_and_updates_both_chips():
    """The page must have a function that recomputes both badges from the
    current DOM. Without this the labels stay stale after add/delete."""
    js = _read_js()
    assert "function refreshKeyCounts" in js, (
        "refreshKeyCounts() helper missing — badges will not update on add/delete"
    )
    # Make sure both chip ids are touched.
    assert 'getElementById("providerCountSummary")' in js
    assert 'getElementById("configuredCountSummary")' in js


def test_refresh_key_counts_uses_distinct_semantics_for_provider_vs_configured():
    """The two badges MUST distinguish 'has a key entered' from 'has a value
    saved'. Otherwise they remain redundantly identical (ISSUE-004)."""
    js = _read_js()
    # Heuristic: the function should evaluate both the key field and either
    # the existing-saved flag or the value field length to bump 'configured'
    # separately from 'providers'.
    func_match = re.search(
        r"function refreshKeyCounts\(\)\s*\{(?P<body>.*?)\n {4}\}",
        js,
        flags=re.S,
    )
    assert func_match, "refreshKeyCounts body not found"
    body = func_match.group("body")
    assert "providers" in body and "configured" in body
    # Configured logic must check value content or existing-saved flag.
    assert (
        'dataset.existing === "true"' in body
        or "wasSaved" in body
        or ".value.length" in body
    ), "configured count must depend on value/existing state, not just key presence"


def test_refresh_key_counts_called_after_add_delete_and_value_input():
    """The badges must update on every state-change path: addRow,
    deleteRow, value input. Otherwise they go stale."""
    js = _read_js()
    # addRow wires both name-input and value-input listeners that call refresh.
    add_match = re.search(
        r"function addRow\([^)]*\)\s*\{(?P<body>.*?)\n {4}\}",
        js,
        flags=re.S,
    )
    assert add_match, "addRow function not found"
    add_body = add_match.group("body")
    assert add_body.count("refreshKeyCounts()") >= 2, (
        "addRow should call refreshKeyCounts at least twice "
        "(after appending the row and inside an input listener)"
    )
    delete_match = re.search(
        r"function deleteRow\([^)]*\)\s*\{(?P<body>.*?)\n {4}\}",
        js,
        flags=re.S,
    )
    assert delete_match, "deleteRow function not found"
    assert "refreshKeyCounts()" in delete_match.group("body")


def test_save_generic_keys_marks_empty_value_input_aria_invalid():
    """On submit, an empty new-row value must produce an inline aria-invalid
    + validation-message on the field — not just a corner toast (ISSUE-005)."""
    js = _read_js()
    save_match = re.search(
        r"async function saveGenericKeys\(\)\s*\{(?P<body>.*?)\n {4}\}",
        js,
        flags=re.S,
    )
    assert save_match, "saveGenericKeys function not found"
    body = save_match.group("body")
    # Must collect inputs (not just a boolean) and mark them invalid.
    assert "missingValueInputs" in body or "missingValueInput" in body, (
        "saveGenericKeys should track WHICH inputs were empty so it can mark them"
    )
    assert 'setAttribute("aria-invalid", "true")' in body, (
        "Empty value inputs must get aria-invalid='true' on submit"
    )
    assert "validation-message" in body, (
        "An inline validation-message element must be inserted/used"
    )
    # Toast still fires for visual users.
    assert "Please enter a value for new API keys" in body
    # Focus moves to the first invalid input so keyboard users land there.
    assert ".focus()" in body


def test_save_generic_clears_prior_aria_invalid_at_start_of_each_submit():
    """Each new submit must clear stale aria-invalid from the previous run
    so a fixed input doesn't keep its old error state visually."""
    js = _read_js()
    save_match = re.search(
        r"async function saveGenericKeys\(\)\s*\{(?P<body>.*?)\n {4}\}",
        js,
        flags=re.S,
    )
    assert save_match
    body = save_match.group("body")
    assert 'setAttribute("aria-invalid", "false")' in body, (
        "saveGenericKeys must reset aria-invalid='false' on every submit "
        "before re-validating, otherwise old errors stick around."
    )
