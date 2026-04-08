# pyright: reportMissingImports=false
"""Template structure snapshot tests."""

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


# ---------------------------------------------------------------------------
# JTN-222: Unlabeled form controls — accessibility labels
# ---------------------------------------------------------------------------


def test_playlist_refresh_interval_has_aria_label(client):
    """The interval number input in the refresh settings form has an aria-label."""
    resp = client.get("/playlist")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    # The refresh_settings_form.html is included inside the Refresh Settings modal.
    # It renders with prefix="modal", so the input id is "modal-interval".
    assert 'name="interval"' in html
    assert 'aria-label="Refresh interval"' in html


def test_playlist_refresh_unit_has_aria_label(client):
    """The unit select in the refresh settings form has an aria-label."""
    resp = client.get("/playlist")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'name="unit"' in html
    assert 'aria-label="Refresh interval unit"' in html


def test_playlist_refresh_time_has_aria_label(client):
    """The refreshTime time input in the refresh settings form has an aria-label."""
    resp = client.get("/playlist")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'name="refreshTime"' in html
    assert 'aria-label="Daily refresh time"' in html


def test_calendar_url_input_has_aria_label(client):
    """The calendarURLs[] input in the calendar plugin page has an aria-label."""
    resp = client.get("/plugin/calendar")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'name="calendarURLs[]"' in html
    assert 'aria-label="Calendar URL"' in html
