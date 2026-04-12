"""JTN-383: API Keys row inputs must have id/name/aria-label (or <label for>).

Server-rendered rows were partially labeled but missing id/name; JS-built rows
(``addRow()`` in ``api_keys_page.js``) were fully bare, so screen readers and
browser autofill could not distinguish them.
"""

from pathlib import Path

# --- Server-rendered rows (Jinja loop) ---


def test_server_rendered_api_keys_rows_have_id_name_and_aria_label(
    client, tmp_path, monkeypatch
):
    """Each row in the server-rendered /api-keys response must have id, name,
    and aria-label on both the key input and the value input."""
    env_file = tmp_path / ".env"
    env_file.write_text("OPEN_AI_SECRET=openai-123\nNASA_SECRET=nasa-456\n")
    monkeypatch.setattr("blueprints.apikeys.get_env_path", lambda: str(env_file))

    resp = client.get("/api-keys")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    # Stable per-row id/name scheme for at least the first two rows.
    assert 'id="apikey-name-0"' in html
    assert 'name="apikey-name-0"' in html
    assert 'id="apikey-value-0"' in html
    assert 'name="apikey-value-0"' in html
    assert 'id="apikey-name-1"' in html
    assert 'id="apikey-value-1"' in html

    # Existing aria-labels preserved (no regression from JTN-309/382 work).
    assert 'aria-label="OPEN_AI_SECRET key name"' in html
    assert 'aria-label="OPEN_AI_SECRET value, hidden"' in html
    assert 'aria-label="NASA_SECRET key name"' in html


# --- JS-built rows (api_keys_page.js addRow) ---


def _js_path() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "src"
        / "static"
        / "scripts"
        / "api_keys_page.js"
    )


def test_api_keys_page_js_addrow_sets_id_name_and_aria_label():
    """addRow() must set id, name, and aria-label on both inputs (JTN-383)."""
    js = _js_path().read_text(encoding="utf-8")

    # id/name pattern — scoped to the JS-built row so every added row is unique.
    assert "keyInput.id = `apikey-name-${suffix}`" in js
    assert "keyInput.name = `apikey-name-${suffix}`" in js
    assert "valInput.id = `apikey-value-${suffix}`" in js
    assert "valInput.name = `apikey-value-${suffix}`" in js

    # Initial aria-label on the key input.
    assert 'keyInput.setAttribute("aria-label", "API key name")' in js


def test_api_keys_page_js_has_dynamic_aria_label_updater():
    """The value input's aria-label must track the current key name (JTN-383).

    ``updateRowAriaLabels`` is wired as an input listener on the key input so
    the screen-reader label for the value stays meaningful as the user types.
    """
    js = _js_path().read_text(encoding="utf-8")

    assert "function updateRowAriaLabels(row, keyName)" in js
    assert "`API key value for ${trimmed}`" in js
    assert "`Delete ${trimmed} API key`" in js
    # Wired up on input events.
    assert 'keyInput.addEventListener("input"' in js


def test_api_keys_page_js_removes_generic_delete_aria_label():
    """The old generic ``Delete API key`` aria-label must no longer be the
    sole setting — it's now computed dynamically via updateRowAriaLabels."""
    js = _js_path().read_text(encoding="utf-8")

    # The generic fallback is now "Delete API key row" (set by updateRowAriaLabels
    # when there is no key name yet). The old literal that ignored the key must
    # not be the only labeling path anymore.
    assert 'delBtn.setAttribute("aria-label", "Delete API key")' not in js
    assert '"Delete API key row"' in js
