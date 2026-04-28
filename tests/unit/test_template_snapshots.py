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
def test_all_pages_include_sidebar_system_footer(client, monkeypatch, path):
    """All main pages keep the bottom-left online/load footer visible."""
    monkeypatch.setattr("os.getloadavg", lambda: (0.0, 0.0, 0.0), raising=False)

    resp = client.get(path)
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert 'class="sys-row"' in html
    assert 'class="sys-stats"' in html
    assert 'id="sidebarOnlineLabel">online</span>' in html
    assert 'class="sys-load" aria-label="Load average">0.00 avg</span>' in html


def test_plugin_page_keeps_progress_timer_contract(client):
    """Plugin pages keep the elapsed timer and progress log hooks present."""
    resp = client.get("/plugin/clock")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert 'id="requestProgress"' in html
    assert 'id="requestProgressClock" class="value">—</span>' in html
    assert 'id="requestProgressElapsed" class="value">0s</span>' in html
    assert 'id="requestProgressList" class="progress-log" aria-live="polite"' in html


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
    assert 'aria-label="Calendar URL 1"' in html


# ---------------------------------------------------------------------------
# JTN-382: Existing-secret inputs must use type=password, not bullet chars
# ---------------------------------------------------------------------------


def test_api_keys_existing_row_uses_password_input(client):
    """Existing-key rows render as type=password with empty value (JTN-382).

    The old implementation used type=text with literal U+25CF bullet characters
    as the value, which breaks screen readers, password managers, and copy-paste.
    The fix renders type=password with value="" and placeholder="(unchanged)".
    """
    from unittest.mock import patch

    fake_entries = [("MY_API_KEY", "supersecret")]

    with patch("blueprints.apikeys.parse_env_file", return_value=fake_entries):
        resp = client.get("/api-keys")

    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    # Must use type=password for the value column
    assert 'type="password"' in html

    # Must NOT contain the U+25CF bullet-character hack
    assert "\u25cf" not in html.lower()

    # The secret value itself must not appear in the HTML source
    assert "supersecret" not in html

    # The empty-value + placeholder pattern must be present
    # JTN-722 widened the placeholder from "(unchanged)" to a more explicit
    # "(leave blank to keep current)" once existing rows became editable.
    assert 'placeholder="(leave blank to keep current)"' in html
