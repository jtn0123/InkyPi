"""Tests for empty-state UX on playlist pages (JTN-151, JTN-172)."""


def test_playlist_display_next_hidden_when_empty(client, device_config_dev):
    """Display Next button should not render for empty playlists."""
    pm = device_config_dev.get_playlist_manager()
    pm.add_playlist("Empty", "06:00", "09:00")
    device_config_dev.write_config()

    resp = client.get("/playlist")
    assert resp.status_code == 200
    html = resp.data.decode()

    # The playlist card should exist
    assert 'data-playlist-name="Empty"' in html
    # But no Display Next button should appear (no plugins)
    assert "Display Next" not in html


def test_playlist_display_next_shown_when_has_plugins(client, device_config_dev):
    """Display Next button should render for playlists with plugins."""
    pm = device_config_dev.get_playlist_manager()
    pm.add_playlist("WithPlugins", "06:00", "09:00")
    pl = pm.get_playlist("WithPlugins")
    pl.add_plugin(
        {
            "plugin_id": "clock",
            "name": "MyClock",
            "plugin_settings": {},
            "refresh": {"interval": 60},
        }
    )
    device_config_dev.write_config()

    resp = client.get("/playlist")
    assert resp.status_code == 200
    html = resp.data.decode()

    assert 'data-playlist-name="WithPlugins"' in html
    assert "Display Next" in html


def test_playlist_display_next_mixed(client, device_config_dev):
    """Display Next appears only for the playlist that has plugins."""
    pm = device_config_dev.get_playlist_manager()
    pm.add_playlist("HasItems", "00:00", "12:00")
    pm.add_playlist("NoItems", "12:00", "24:00")
    pl = pm.get_playlist("HasItems")
    pl.add_plugin(
        {
            "plugin_id": "clock",
            "name": "MyClock",
            "plugin_settings": {},
            "refresh": {"interval": 60},
        }
    )
    device_config_dev.write_config()

    resp = client.get("/playlist")
    assert resp.status_code == 200
    html = resp.data.decode()

    # Both cards present
    assert 'data-playlist-name="HasItems"' in html
    assert 'data-playlist-name="NoItems"' in html

    # Display Next should appear exactly once (only for HasItems)
    assert html.count("Display Next") == 1
    assert 'data-playlist="HasItems"' in html
