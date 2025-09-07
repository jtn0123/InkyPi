import re

import pytest


@pytest.fixture()
def icons_csp_env(monkeypatch):
    # Allow @phosphor-icons/web stylesheet and remote fonts in CSP during tests
    monkeypatch.setenv(
        "INKYPI_CSP",
        "default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline' https://unpkg.com; script-src 'self'; font-src 'self' data: https:",
    )
    return True


def _html(client, path: str) -> str:
    resp = client.get(path)
    assert resp.status_code == 200
    data = getattr(resp, "data", b"")
    if isinstance(data, (bytes, bytearray)):
        return data.decode("utf-8", errors="ignore")
    # Fallback for test clients that return string bodies
    return str(data)


def test_home_includes_phosphor_and_icons(icons_csp_env, client):
    html = _html(client, "/")
    assert "@phosphor-icons/web" in html
    # Header icons we render on home
    assert "ph-squares-four" in html  # playlists
    assert "ph-gear-six" in html      # settings
    assert "ph-clock-counter-clockwise" in html  # history
    # Theme toggle present
    assert 'id="themeToggle"' in html


def test_playlist_icons_present(icons_csp_env, client):
    # Ensure there is at least one playlist and plugin so action icons render
    app = client.application
    device_config = app.config["DEVICE_CONFIG"]
    pm = device_config.get_playlist_manager()
    pm.add_playlist("P", "00:00", "24:00")
    pm.add_plugin_to_playlist(
        "P",
        {
            "plugin_id": "ai_text",
            "name": "inst",
            "plugin_settings": {"title": "T"},
            "refresh": {"interval": 60},
        },
    )
    device_config.write_config()

    html = _html(client, "/playlist")
    # Header playlists icon
    assert "ph-squares-four" in html
    # Action buttons
    assert "ph-pencil-simple" in html
    assert "ph-monitor" in html
    assert "ph-trash" in html


def test_settings_icons_and_toggle(icons_csp_env, client):
    html = _html(client, "/settings")
    assert "@phosphor-icons/web" in html
    assert "ph-gear-six" in html
    assert 'id="themeToggle"' in html


def test_history_icon_present(icons_csp_env, client):
    html = _html(client, "/history")
    assert "ph-clock-counter-clockwise" in html


def test_api_keys_icon_present(icons_csp_env, client):
    html = _html(client, "/settings/api-keys")
    assert "ph-gear-six" in html


def test_csp_allows_unpkg(icons_csp_env, client):
    resp = client.get("/")
    csp = resp.headers.get("Content-Security-Policy-Report-Only") or resp.headers.get(
        "Content-Security-Policy"
    )
    assert csp is not None
    assert "https://unpkg.com" in csp


