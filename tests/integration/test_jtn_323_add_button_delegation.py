"""Tests for JTN-323: + Add API Key button must use data-api-action delegation."""


def test_add_button_has_data_api_action_attribute(client):
    """JTN-323: the + Add API Key button must have data-api-action='add-row'."""
    resp = client.get("/api-keys")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert (
        'data-api-action="add-row"' in html
    ), "Add API Key button must use data-api-action='add-row' for delegation"


def test_js_delegation_handler_covers_add_row_action(client):
    """JTN-323: the delegated click handler must handle the 'add-row' action."""
    resp = client.get("/static/scripts/api_keys_page.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    assert '"add-row"' in js, "JS must include an 'add-row' action case"
    assert "addRow()" in js, "The 'add-row' action must call addRow()"


def test_add_button_has_both_id_and_data_action(client):
    """JTN-323: the button should have both id and data-api-action for robustness."""
    resp = client.get("/api-keys")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert 'id="addApiKeyBtn"' in html
    assert 'data-api-action="add-row"' in html
