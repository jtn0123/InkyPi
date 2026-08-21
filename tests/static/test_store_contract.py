"""Contract tests for src/static/scripts/store.js (JTN-502).

Verifies that the public API surface (`createStore`, `get`, `set`, `subscribe`)
is present and that the global is exposed as `window.InkyPiStore`.
"""

from flask.testing import FlaskClient


def test_store_script_exists_and_is_served(client: FlaskClient) -> None:
    resp = client.get("/static/scripts/store.js")
    assert resp.status_code == 200


def test_store_exposes_create_store_function(client: FlaskClient) -> None:
    resp = client.get("/static/scripts/store.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    assert "function createStore(" in js


def test_store_exposes_get_method(client: FlaskClient) -> None:
    resp = client.get("/static/scripts/store.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    assert "function get(" in js


def test_store_exposes_set_method(client: FlaskClient) -> None:
    resp = client.get("/static/scripts/store.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    assert "function set(" in js


def test_store_exposes_subscribe_method(client: FlaskClient) -> None:
    resp = client.get("/static/scripts/store.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    assert "function subscribe(" in js


def test_store_registers_global_on_window(client: FlaskClient) -> None:
    resp = client.get("/static/scripts/store.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    assert "window.InkyPiStore" in js
    assert "createStore" in js


def test_store_registers_global_on_globalthis(client: FlaskClient) -> None:
    resp = client.get("/static/scripts/store.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    assert "globalThis.InkyPiStore" in js


def test_store_supports_function_updater(client: FlaskClient) -> None:
    """set() must accept a function updater, not just a plain object."""
    resp = client.get("/static/scripts/store.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    assert "typeof updater === 'function'" in js


def test_store_subscribe_returns_unsubscribe(client: FlaskClient) -> None:
    """subscribe() must return an unsubscribe function."""
    resp = client.get("/static/scripts/store.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    assert "function unsubscribe()" in js


def test_dashboard_page_uses_store(client: FlaskClient) -> None:
    """dashboard_page.js must reference InkyPiStore after JTN-502 migration."""
    resp = client.get("/static/scripts/dashboard_page.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    assert "InkyPiStore" in js


def test_plugin_form_uses_store(client: FlaskClient) -> None:
    """plugin_form.js must reference InkyPiStore after JTN-502 migration."""
    resp = client.get("/static/scripts/plugin_form.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    assert "InkyPiStore" in js


def test_settings_page_uses_store(client: FlaskClient) -> None:
    """settings_page.js must reference InkyPiStore after JTN-502 migration."""
    resp = client.get("/static/scripts/settings_page.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    assert "InkyPiStore" in js
