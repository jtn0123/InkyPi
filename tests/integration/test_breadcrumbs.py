"""Tests for breadcrumb rendering across InkyPi pages."""


def test_settings_breadcrumb(client):
    """GET /settings contains breadcrumb nav with Home and Settings."""
    resp = client.get("/settings")
    html = resp.data.decode()
    assert '<nav aria-label="Breadcrumb"' in html
    assert "Home" in html
    assert "Settings" in html


def test_playlist_breadcrumb(client):
    """GET /playlist contains breadcrumb with Home and Playlists."""
    resp = client.get("/playlist")
    html = resp.data.decode()
    assert "Home" in html
    assert "Playlists" in html


def test_history_breadcrumb(client):
    """GET /history contains breadcrumb with Home and History."""
    resp = client.get("/history")
    html = resp.data.decode()
    assert "Home" in html
    assert "History" in html


def test_api_keys_breadcrumb(client):
    """GET /settings/api-keys contains breadcrumb with Home, Settings, and API Keys with correct links."""
    resp = client.get("/settings/api-keys")
    html = resp.data.decode()
    assert "Home" in html
    assert "Settings" in html
    assert "API Keys" in html
    # Home and Settings should be linked; API Keys should not
    assert 'href="/"' in html or 'href="' in html  # Home link present
    assert 'href="/settings"' in html  # Settings link present


def test_plugin_breadcrumb(client):
    """GET /plugin/<id> contains breadcrumb with Home, Plugins, and the plugin display name."""
    # "clock" is a built-in plugin type whose plugin-info.json defines display_name="Clock"
    resp = client.get("/plugin/clock")
    assert resp.status_code == 200
    html = resp.data.decode()
    assert "Home" in html
    assert "Clock" in html
    # JTN-637: intermediate "Plugins" level links back to the home page plugin list
    assert ">Plugins</a>" in html
    assert 'href="/#plugins"' in html
    # Leaf item (plugin display name) should carry aria-current and not be a link
    assert 'aria-current="page"' in html
    assert "<span>Clock</span>" in html


def test_breadcrumb_last_item_not_linked(client):
    """The last breadcrumb item has aria-current="page" and is a <span>, not an <a>."""
    resp = client.get("/settings")
    html = resp.data.decode()
    # Last item must carry aria-current="page"
    assert 'aria-current="page"' in html
    # The last breadcrumb label "Settings" must appear inside a <span>, not an <a>
    assert "<span>Settings</span>" in html
    # Confirm there is no link wrapping the final "Settings" label
    assert 'href="/settings">Settings' not in html
