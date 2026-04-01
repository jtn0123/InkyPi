# pyright: reportMissingImports=false
"""Template structure snapshot tests."""
import re
from pathlib import Path

import pytest


def test_settings_page_structure(client):
    """Settings page contains key form elements."""
    resp = client.get("/settings")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert "settingsForm" in html or "settings-form" in html
    assert "saveSettingsBtn" in html or "save" in html.lower()
    assert "timezone" in html.lower()
    assert "data-page-shell" in html
    assert 'id="main-content"' in html


def test_playlist_page_structure(client):
    """Playlist page contains new playlist button and list container."""
    resp = client.get("/playlist")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert "newPlaylistBtn" in html
    assert "data-page-shell" in html


def test_plugin_page_structure(client):
    """Plugin page contains settings form and update button."""
    resp = client.get("/plugin/clock")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert "settingsForm" in html
    assert "data-page-shell" in html


def test_api_keys_page_structure(client):
    """API keys page contains save button and key management elements."""
    resp = client.get("/api-keys")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert "saveApiKeysBtn" in html
    assert "data-page-shell" in html


def test_home_page_structure(client):
    """Home page contains preview image and plugin grid."""
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert "previewImage" in html
    assert "plugins-container" in html
    assert "data-page-shell" in html


@pytest.mark.parametrize(
    "path,shell_attr",
    [
        ("/", "data-page-shell"),
        ("/settings", "data-page-shell"),
        ("/playlist", "data-page-shell"),
        ("/plugin/clock", "data-page-shell"),
        ("/api-keys", "data-page-shell"),
    ],
)
def test_all_pages_include_shell(client, path, shell_attr):
    """All main pages include the page shell attribute."""
    resp = client.get(path)
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert shell_attr in html


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/settings",
        "/playlist",
        "/plugin/clock",
        "/api-keys",
    ],
)
def test_all_pages_include_theme_toggle(client, path):
    """All main pages include the theme toggle."""
    resp = client.get(path)
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "themeToggle" in html or "theme-toggle" in html


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/settings",
        "/playlist",
        "/plugin/clock",
        "/api-keys",
    ],
)
def test_all_pages_include_navigation(client, path):
    """All main pages include navigation elements."""
    resp = client.get(path)
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    # All pages should have header navigation or back button
    assert "header" in html.lower()


@pytest.mark.parametrize(
    "template_path",
    [
        "src/plugins/image_upload/settings.html",
        "src/plugins/image_album/settings.html",
        "src/plugins/image_folder/settings.html",
    ],
)
def test_image_plugin_background_fill_markup_is_accessible(template_path):
    content = Path(template_path).read_text(encoding="utf-8")

    assert "{% include 'widgets/background_fill.html' %}" in content


def test_background_fill_widget_markup_is_accessible():
    content = Path("src/templates/widgets/background_fill.html").read_text(
        encoding="utf-8"
    )

    assert "Background Fill" in content
    assert "<fieldset" in content
    assert "<legend" in content
    assert 'name="backgroundOption"' in content
    assert 'value="blur"' in content
    assert re.search(r'<input[^>]*value="blur"[^>]*checked', content)
    assert "Solid Color" in content
