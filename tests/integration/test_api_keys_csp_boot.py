"""Regression tests for JTN-325, JTN-324, JTN-323: API Keys page buttons.

Root cause: the page boot config lived in an inline <script> block that CSP
``script-src 'self'`` silently blocked in production.  The fix moves the boot
config to ``data-*`` attributes on the page container and has the external JS
self-initialise from the DOM, eliminating the need for inline JS.
"""

from __future__ import annotations

import re  # noqa: I001 — re is used below; import order is intentional

# -- JTN-323: + Add API Key button must work ----------------------------------


def test_no_inline_script_in_api_keys_page(client):
    """The api_keys page must not contain an inline <script> boot block.

    CSP ``script-src 'self'`` blocks inline scripts, which silently
    prevented all button handlers from initialising (JTN-323/324/325).
    """
    resp = client.get("/api-keys")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    # The old pattern was: <script> window.__INKYPI_API_KEYS_BOOT__ = ...
    assert (
        "__INKYPI_API_KEYS_BOOT__" not in html
    ), "Inline boot config must be removed; use data-* attributes instead"


def test_api_keys_frame_has_data_attributes(client):
    """The .api-keys-frame container must carry data-* boot config attributes."""
    resp = client.get("/api-keys")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert "data-delete-managed-url=" in html
    assert "data-mode=" in html
    assert "data-save-generic-url=" in html
    assert "data-save-managed-url=" in html


def test_js_self_initialises_from_data_attributes(client):
    """The external JS must read data-* attributes and self-initialise."""
    resp = client.get("/static/scripts/api_keys_page.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    assert "autoInit" in js, "JS must contain an autoInit function"
    assert ".api-keys-frame" in js, "JS must query the frame element for data-* attrs"
    assert "dataset" in js, "JS must read data-* attributes via dataset"


# -- JTN-324: Suggested key chips must trigger row creation --------------------


def test_preset_buttons_use_delegation(client):
    """JTN-324: preset chip buttons must use data-api-action='add-preset'."""
    resp = client.get("/api-keys")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    preset_count = html.count('data-api-action="add-preset"')
    assert (
        preset_count >= 6
    ), f"Expected at least 6 preset chip buttons, found {preset_count}"


def test_js_handles_add_preset_action(client):
    """JTN-324: the delegated click handler must handle the 'add-preset' action."""
    resp = client.get("/static/scripts/api_keys_page.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    assert '"add-preset"' in js, "JS must include an 'add-preset' action case"
    assert "addPreset" in js, "The 'add-preset' action must call addPreset"


# -- JTN-325: Delete button must confirm and remove entries --------------------


def test_delete_button_uses_delegation(client):
    """JTN-325: delete buttons in generic mode use data-api-action='delete-row'."""
    # Verify the JS handler supports both delete actions
    js_resp = client.get("/static/scripts/api_keys_page.js")
    js = js_resp.get_data(as_text=True)

    assert '"delete-row"' in js, "JS must handle 'delete-row' action"
    assert '"delete-key"' in js, "JS must handle 'delete-key' action for managed mode"


def test_external_js_loaded_with_defer(client):
    """The api_keys_page.js script tag must use defer (not inline) for CSP compat."""
    resp = client.get("/api-keys")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    pattern = re.compile(r"<script[^>]*api_keys_page\.js[^>]*defer[^>]*>")
    assert pattern.search(
        html
    ), "api_keys_page.js must be loaded via a <script defer> tag"


def test_data_mode_attribute_matches_generic(client):
    """The generic API keys page must set data-mode='generic'."""
    resp = client.get("/api-keys")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert (
        'data-mode="generic"' in html
    ), "data-mode attribute must reflect the actual api_keys_mode"
