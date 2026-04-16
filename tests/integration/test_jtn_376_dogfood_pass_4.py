"""JTN-376: Dogfood pass 4 — validation and UX fixes.

Tests cover the server-side plugin validation added to ai_image, ai_text,
countdown, and image_url, the client-side refresh-settings range check, and
the API keys page accessibility improvements.
"""

import json

# ---------------------------------------------------------------------------
# Theme 3 — Plugin validation: AI Image
# ---------------------------------------------------------------------------


def test_ai_image_save_rejects_empty_prompt(client):
    resp = client.post(
        "/save_plugin_settings",
        data={"plugin_id": "ai_image", "textPrompt": ""},
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert "Prompt" in data.get("error", "")


def test_ai_image_save_rejects_invalid_provider(client):
    resp = client.post(
        "/save_plugin_settings",
        data={"plugin_id": "ai_image", "textPrompt": "A cat", "provider": "badprovider"},
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert "provider" in data.get("error", "").lower()


def test_ai_image_save_rejects_invalid_model(client):
    resp = client.post(
        "/save_plugin_settings",
        data={
            "plugin_id": "ai_image",
            "textPrompt": "A cat",
            "imageModel": "not-a-model",
        },
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert "model" in data.get("error", "").lower()


def test_ai_image_save_accepts_valid_settings(client):
    resp = client.post(
        "/save_plugin_settings",
        data={
            "plugin_id": "ai_image",
            "textPrompt": "A beautiful sunset",
            "provider": "openai",
            "imageModel": "gpt-image-1.5",
        },
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Theme 3 — Plugin validation: AI Text
# ---------------------------------------------------------------------------


def test_ai_text_save_rejects_empty_prompt(client):
    resp = client.post(
        "/save_plugin_settings",
        data={"plugin_id": "ai_text", "textPrompt": "", "textModel": "gpt-5-nano"},
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert "Prompt" in data.get("error", "")


def test_ai_text_save_rejects_missing_model(client):
    resp = client.post(
        "/save_plugin_settings",
        data={"plugin_id": "ai_text", "textPrompt": "Hello", "textModel": ""},
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert "Model" in data.get("error", "")


def test_ai_text_save_rejects_invalid_provider(client):
    resp = client.post(
        "/save_plugin_settings",
        data={
            "plugin_id": "ai_text",
            "textPrompt": "Hello",
            "textModel": "gpt-5-nano",
            "provider": "badprovider",
        },
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert "provider" in data.get("error", "").lower()


def test_ai_text_save_accepts_valid_settings(client):
    resp = client.post(
        "/save_plugin_settings",
        data={
            "plugin_id": "ai_text",
            "textPrompt": "Summarize today's news",
            "textModel": "gpt-5-nano",
            "provider": "openai",
        },
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Theme 3 — Plugin validation: Countdown
# ---------------------------------------------------------------------------


def test_countdown_save_rejects_invalid_date_format(client):
    resp = client.post(
        "/save_plugin_settings",
        data={"plugin_id": "countdown", "title": "Trip", "date": "not-a-date"},
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert "date" in data.get("error", "").lower() or "Date" in data.get("error", "")


def test_countdown_save_accepts_valid_date(client):
    resp = client.post(
        "/save_plugin_settings",
        data={"plugin_id": "countdown", "title": "Trip", "date": "2030-01-01"},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Theme 3 — Plugin validation: Image URL
# ---------------------------------------------------------------------------


def test_image_url_save_rejects_empty_url(client):
    resp = client.post(
        "/save_plugin_settings",
        data={"plugin_id": "image_url", "url": ""},
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert "URL" in data.get("error", "") or "required" in data.get("error", "").lower()


def test_image_url_save_rejects_non_http_url(client):
    resp = client.post(
        "/save_plugin_settings",
        data={"plugin_id": "image_url", "url": "ftp://example.com/image.png"},
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert "http" in data.get("error", "").lower()


def test_image_url_save_rejects_nonsense_url(client):
    resp = client.post(
        "/save_plugin_settings",
        data={"plugin_id": "image_url", "url": "not-a-url"},
    )
    assert resp.status_code == 400


def test_image_url_save_accepts_valid_url(client):
    resp = client.post(
        "/save_plugin_settings",
        data={"plugin_id": "image_url", "url": "https://example.com/image.jpg"},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Theme 2 — Refresh Settings interval range validation (server-side)
# ---------------------------------------------------------------------------


def test_add_plugin_rejects_interval_above_999(client, device_config_dev):
    pm = device_config_dev.get_playlist_manager()
    if not pm.get_playlist("Default"):
        pm.add_playlist("Default", "00:00", "24:00")
    device_config_dev.write_config()

    resp = client.post(
        "/add_plugin",
        data={
            "plugin_id": "clock",
            "refresh_settings": json.dumps({
                "refreshType": "interval",
                "interval": "5000",
                "unit": "minute",
                "playlist": "Default",
                "instance_name": "HighInterval",
            }),
        },
    )
    assert resp.status_code == 422
    body = resp.get_json() or {}
    assert "between 1 and 999" in (body.get("error") or body.get("message") or "")


def test_add_plugin_rejects_interval_zero(client, device_config_dev):
    pm = device_config_dev.get_playlist_manager()
    if not pm.get_playlist("Default"):
        pm.add_playlist("Default", "00:00", "24:00")
    device_config_dev.write_config()

    resp = client.post(
        "/add_plugin",
        data={
            "plugin_id": "clock",
            "refresh_settings": json.dumps({
                "refreshType": "interval",
                "interval": "0",
                "unit": "minute",
                "playlist": "Default",
                "instance_name": "ZeroInterval",
            }),
        },
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Theme 4 — API Keys page: value input type=password in JS addRow
# ---------------------------------------------------------------------------


def test_api_keys_page_js_addrow_uses_password_type():
    """JS-built API key rows must use type=password for value inputs."""
    from pathlib import Path

    js_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "static"
        / "scripts"
        / "api_keys_page.js"
    )
    js = js_path.read_text(encoding="utf-8")
    # The valInput must use type="password", not type="text"
    assert 'valInput.type = "password"' in js
    assert 'valInput.type = "text"' not in js


# ---------------------------------------------------------------------------
# Theme 5 — RefreshSettingsManager interval validation (JS)
# ---------------------------------------------------------------------------


def test_refresh_settings_manager_js_validates_interval_range():
    """The JS RefreshSettingsManager must check interval upper bound (999)."""
    from pathlib import Path

    js_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "static"
        / "scripts"
        / "refresh_settings_manager.js"
    )
    js = js_path.read_text(encoding="utf-8")
    # Must check for interval > 999
    assert "999" in js
    assert "between 1 and 999" in js


# ---------------------------------------------------------------------------
# Theme 5 — Diagnostics: human-readable benchmark + isolation messages
# ---------------------------------------------------------------------------


def test_settings_page_js_benchmark_empty_state_message():
    """When no benchmark data exists, show a human message instead of null JSON."""
    from pathlib import Path

    js_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "static"
        / "scripts"
        / "settings_page.js"
    )
    js = js_path.read_text(encoding="utf-8")
    assert "No benchmark data recorded" in js


def test_settings_page_js_isolation_human_messages():
    """Isolation actions should show human-readable messages."""
    from pathlib import Path

    js_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "static"
        / "scripts"
        / "settings_page.js"
    )
    js = js_path.read_text(encoding="utf-8")
    assert "has been isolated" in js
    assert "has been un-isolated" in js
    assert "not a registered plugin" in js
