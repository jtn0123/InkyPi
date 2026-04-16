"""JTN-376: Dogfood pass 4 — validation and UX fixes.

Tests cover the server-side plugin validation added to ai_image, ai_text,
countdown, and image_url, the client-side refresh-settings range check, and
the API keys page accessibility improvements.
"""

import json
from pathlib import Path

import pytest

# Root path to the JS scripts directory (resolved once).
_JS_DIR = Path(__file__).resolve().parents[2] / "src" / "static" / "scripts"


def _read_js_asset(filename: str) -> str:
    """Return the contents of a JS asset from src/static/scripts."""
    return (_JS_DIR / filename).read_text(encoding="utf-8")


def _save_plugin(client, data, *, expect_status=400):
    """POST to /save_plugin_settings and return (response, json_body)."""
    resp = client.post("/save_plugin_settings", data=data)
    assert resp.status_code == expect_status
    return resp, resp.get_json() or {}


# ---------------------------------------------------------------------------
# Theme 3 — Plugin validation (parametrized rejection cases)
# ---------------------------------------------------------------------------

_REJECT_CASES = [
    (
        "ai_image_empty_prompt",
        {"plugin_id": "ai_image", "textPrompt": ""},
        "Prompt",
    ),
    (
        "ai_image_invalid_provider",
        {"plugin_id": "ai_image", "textPrompt": "A cat", "provider": "badprovider"},
        "provider",
    ),
    (
        "ai_image_invalid_model",
        {"plugin_id": "ai_image", "textPrompt": "A cat", "imageModel": "not-a-model"},
        "model",
    ),
    (
        "ai_image_mismatched_provider_model",
        {
            "plugin_id": "ai_image",
            "textPrompt": "A cat",
            "provider": "google",
            "imageModel": "gpt-image-1.5",
        },
        "provider",
    ),
    (
        "ai_text_empty_prompt",
        {"plugin_id": "ai_text", "textPrompt": "", "textModel": "gpt-5-nano"},
        "Prompt",
    ),
    (
        "ai_text_missing_model",
        {"plugin_id": "ai_text", "textPrompt": "Hello", "textModel": ""},
        "Model",
    ),
    (
        "ai_text_invalid_provider",
        {
            "plugin_id": "ai_text",
            "textPrompt": "Hello",
            "textModel": "gpt-5-nano",
            "provider": "badprovider",
        },
        "provider",
    ),
    (
        "countdown_invalid_date",
        {"plugin_id": "countdown", "title": "Trip", "date": "not-a-date"},
        "date",
    ),
    (
        "countdown_missing_date",
        {"plugin_id": "countdown", "title": "Trip", "date": ""},
        "required",
    ),
    (
        "image_url_empty",
        {"plugin_id": "image_url", "url": ""},
        "required",
    ),
    (
        "image_url_non_http",
        {"plugin_id": "image_url", "url": "ftp://example.com/image.png"},
        "http",
    ),
    (
        "image_url_nonsense",
        {"plugin_id": "image_url", "url": "not-a-url"},
        "http",
    ),
]


@pytest.mark.parametrize(
    "form_data, error_substr",
    [(d, s) for _, d, s in _REJECT_CASES],
    ids=[tid for tid, _, _ in _REJECT_CASES],
)
def test_save_plugin_rejects_invalid(client, form_data, error_substr):
    """Plugin validation rejects bad input with a 400 and a descriptive error."""
    _, body = _save_plugin(client, form_data, expect_status=400)
    assert error_substr.lower() in body.get("error", "").lower()


def test_image_url_save_rejects_nonsense_url_with_error_body(client):
    """Nonsense URLs should fail for URL validation, not an unrelated 400."""
    _, body = _save_plugin(
        client,
        {"plugin_id": "image_url", "url": "not-a-url"},
        expect_status=400,
    )
    assert isinstance(body, dict)
    assert "error" in body
    assert "http" in body["error"].lower() or "hostname" in body["error"].lower()


# ---------------------------------------------------------------------------
# Theme 3 — Plugin validation (acceptance cases)
# ---------------------------------------------------------------------------

_ACCEPT_CASES = [
    (
        "ai_image_valid",
        {
            "plugin_id": "ai_image",
            "textPrompt": "A beautiful sunset",
            "provider": "openai",
            "imageModel": "gpt-image-1.5",
        },
    ),
    (
        "ai_text_valid",
        {
            "plugin_id": "ai_text",
            "textPrompt": "Summarize today's news",
            "textModel": "gpt-5-nano",
            "provider": "openai",
        },
    ),
    (
        "countdown_valid",
        {"plugin_id": "countdown", "title": "Trip", "date": "2030-01-01"},
    ),
    (
        "image_url_valid",
        {"plugin_id": "image_url", "url": "https://example.com/image.jpg"},
    ),
]


@pytest.mark.parametrize(
    "form_data",
    [d for _, d in _ACCEPT_CASES],
    ids=[tid for tid, _ in _ACCEPT_CASES],
)
def test_save_plugin_accepts_valid(client, form_data):
    """Valid plugin settings are accepted with a 200."""
    _save_plugin(client, form_data, expect_status=200)


# ---------------------------------------------------------------------------
# Theme 2 — Refresh Settings interval range validation (server-side)
# ---------------------------------------------------------------------------


def _setup_default_playlist(device_config_dev):
    """Ensure a Default playlist exists for interval-rejection tests."""
    pm = device_config_dev.get_playlist_manager()
    if not pm.get_playlist("Default"):
        pm.add_playlist("Default", "00:00", "24:00")
    device_config_dev.write_config()


@pytest.mark.parametrize(
    "interval, instance_name",
    [("5000", "HighInterval"), ("0", "ZeroInterval")],
    ids=["above_999", "zero"],
)
def test_add_plugin_rejects_bad_interval(
    client, device_config_dev, interval, instance_name
):
    _setup_default_playlist(device_config_dev)
    resp = client.post(
        "/add_plugin",
        data={
            "plugin_id": "clock",
            "refresh_settings": json.dumps(
                {
                    "refreshType": "interval",
                    "interval": interval,
                    "unit": "minute",
                    "playlist": "Default",
                    "instance_name": instance_name,
                }
            ),
        },
    )
    assert resp.status_code == 422
    body = resp.get_json() or {}
    assert "between 1 and 999" in (body.get("error") or body.get("message") or "")


# ---------------------------------------------------------------------------
# Theme 4 — API Keys page: value input type=password in JS addRow
# ---------------------------------------------------------------------------


def test_api_keys_page_js_addrow_uses_password_type():
    """JS-built API key rows must use type=password for value inputs."""
    js = _read_js_asset("api_keys_page.js")
    assert 'valInput.type = "password"' in js
    assert 'valInput.type = "text"' not in js


# ---------------------------------------------------------------------------
# Theme 5 — RefreshSettingsManager interval validation (JS)
# ---------------------------------------------------------------------------


def test_refresh_settings_manager_js_validates_interval_range():
    """The JS RefreshSettingsManager must check interval upper bound (999)."""
    js = _read_js_asset("refresh_settings_manager.js")
    assert "999" in js
    assert "between 1 and 999" in js


# ---------------------------------------------------------------------------
# Theme 5 — Diagnostics: human-readable benchmark + isolation messages
# ---------------------------------------------------------------------------


def test_settings_page_js_benchmark_empty_state_message():
    """When no benchmark data exists, show a human message instead of null JSON."""
    js = _read_js_asset("settings_page.js")
    assert "No benchmark data recorded" in js


def test_settings_page_js_isolation_human_messages():
    """Isolation actions should show human-readable messages."""
    js = _read_js_asset("settings_page.js")
    assert "has been ${past}" in js
    assert '"isolated"' in js
    assert '"un-isolate"' in js
    assert "not a registered plugin" in js
