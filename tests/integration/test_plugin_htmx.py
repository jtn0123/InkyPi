# pyright: reportMissingImports=false
"""HTMX integration coverage for the plugin settings form (JTN-506).

Phase 1 scopes HTMX adoption to ``/save_plugin_settings``.  These tests lock
in the request/response contract so future refactors don't regress:

* Requests WITHOUT ``HX-Request`` continue to receive JSON (existing clients,
  test harness, API consumers).
* Requests WITH ``HX-Request: true`` receive HTML partials.  Validation
  errors swap error markup into ``#plugin-form-errors``; successful saves
  return an HTML success partial and set ``HX-Trigger`` so the existing
  toast JS listener can fire.
"""

from __future__ import annotations

import json


def test_save_plugin_settings_htmx_returns_html_on_success(client):
    resp = client.post(
        "/save_plugin_settings",
        data={
            "plugin_id": "ai_text",
            "title": "HTMX Title",
            "textModel": "gpt-4o",
            "textPrompt": "Hello HTMX",
        },
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 200
    content_type = resp.headers.get("Content-Type", "")
    assert "text/html" in content_type
    body = resp.get_data(as_text=True)
    # Success partial uses the .validation-message success class
    assert "validation-message success" in body
    assert "Settings saved" in body
    # HX-Trigger header fires the toast handler registered in plugin_form.js
    trigger_raw = resp.headers.get("HX-Trigger")
    assert trigger_raw, "expected HX-Trigger header on HTMX success"
    trigger = json.loads(trigger_raw)
    assert "pluginSettingsSaved" in trigger


def test_save_plugin_settings_htmx_returns_error_partial_when_plugin_missing(client):
    resp = client.post(
        "/save_plugin_settings",
        data={"plugin_id": "not_real_plugin"},
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 404
    assert "text/html" in resp.headers.get("Content-Type", "")
    body = resp.get_data(as_text=True)
    assert "validation-message error" in body
    assert "data-plugin-form-error" in body
    assert "not_real_plugin" in body


def test_save_plugin_settings_htmx_returns_error_partial_when_plugin_id_missing(client):
    resp = client.post(
        "/save_plugin_settings",
        data={"title": "no plugin id"},
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 422
    assert "text/html" in resp.headers.get("Content-Type", "")
    body = resp.get_data(as_text=True)
    assert "validation-message error" in body
    assert "plugin_id" in body
    assert 'data-plugin-form-error-field="plugin_id"' in body


def test_save_plugin_settings_without_htmx_header_still_returns_json(client):
    """Legacy contract: no HX-Request header => JSON response."""
    resp = client.post(
        "/save_plugin_settings",
        data={
            "plugin_id": "ai_text",
            "title": "JSON still works",
            "textModel": "gpt-4o",
            "textPrompt": "hi",
        },
    )
    assert resp.status_code == 200
    assert "application/json" in resp.headers.get("Content-Type", "")
    payload = resp.get_json()
    assert payload.get("success") is True
    assert "instance_name" in payload


def test_save_plugin_settings_htmx_error_never_leaks_exception_text(
    client, flask_app, monkeypatch
):
    """HTMX error partial should use the generic internal-error copy."""
    dc = flask_app.config["DEVICE_CONFIG"]
    monkeypatch.setattr(
        dc,
        "update_atomic",
        lambda *args, **kwargs: (_ for _ in ()).throw(Exception("secret stack trace")),
    )
    resp = client.post(
        "/save_plugin_settings",
        data={
            "plugin_id": "ai_text",
            "title": "T",
            "textModel": "gpt-4o",
            "textPrompt": "p",
        },
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 500
    body = resp.get_data(as_text=True)
    assert "secret stack trace" not in body
    assert "internal error" in body.lower()


def test_plugin_page_renders_htmx_save_button(client):
    """The plugin page ships hx-* attributes on the Save Settings button."""
    resp = client.get("/plugin/ai_text")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'id="savePluginSettingsBtn"' in body
    assert 'hx-post="/save_plugin_settings"' in body
    assert 'hx-target="#plugin-form-errors"' in body
    assert 'hx-include="#settingsForm"' in body
    # Progressive enhancement: form has action/method for no-JS fallback
    assert 'action="/save_plugin_settings"' in body
    assert 'id="plugin-form-errors"' in body
