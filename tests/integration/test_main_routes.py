# pyright: reportMissingImports=false
import os
import re
from datetime import UTC, datetime

from model import RefreshInfo


def test_main_page(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"/preview" in resp.data


def test_dashboard_header_actions_use_compact_handoff_button_pattern(client):
    resp = client.get("/")
    html = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert 'id="dashboardRefreshBtn"' in html
    assert 'id="displayNextBtn"' in html
    assert 'class="header-button is-secondary dashboard-header-button"' in html
    assert 'class="header-button primary dashboard-header-button"' in html
    assert 'class="action-button is-secondary dashboard-header-button"' not in html
    assert 'class="action-button primary dashboard-header-button"' not in html


def test_preview_size_mode_native_on_home(client, device_config_dev, monkeypatch):
    # native: expect native sizing metadata present for controller-driven preview sizing
    device_config_dev.update_value("preview_size_mode", "native", write=True)
    resp = client.get("/")
    assert resp.status_code == 200
    assert b'data-native-width="' in resp.data and b'data-native-height="' in resp.data
    assert b'id="dashboardStageCopy"' in resp.data


def test_preview_size_mode_fit_on_home(client, device_config_dev, monkeypatch):
    # fit: expect no explicit inline width/height style and still retain metadata
    device_config_dev.update_value("preview_size_mode", "fit", write=True)
    resp = client.get("/")
    assert resp.status_code == 200
    assert b'id="previewImage" style=' not in resp.data
    assert b'data-native-width="' in resp.data


def test_preview_404_when_no_image(client):
    dc = client.application.config["DEVICE_CONFIG"]
    for path in (dc.processed_image_file, dc.current_image_file):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
    resp = client.get("/preview")
    assert resp.status_code == 404


def test_preview_serves_current_image_when_exists(client, device_config_dev):
    # Write a dummy current image
    from PIL import Image

    img = Image.new("RGB", (10, 10), "black")
    img.save(device_config_dev.current_image_file)

    resp = client.get("/preview")
    assert resp.status_code == 200
    assert resp.mimetype == "image/png"


def test_preview_prefers_processed_over_current(client, device_config_dev):
    from PIL import Image

    # Create different colored images to differentiate
    cur = Image.new("RGB", (10, 10), "black")
    cur.save(device_config_dev.current_image_file)
    proc = Image.new("RGB", (10, 10), "white")
    proc.save(device_config_dev.processed_image_file)

    resp = client.get("/preview")
    assert resp.status_code == 200
    assert resp.mimetype == "image/png"


def test_home_now_showing_renders_from_refresh_info(client, device_config_dev):
    # Seed refresh_info in config
    device_config_dev.refresh_info = RefreshInfo(
        refresh_type="Playlist",
        plugin_id="weather",
        refresh_time="2025-01-01T00:00:00",
        image_hash=123,
        playlist="Default",
        plugin_instance="Home Weather",
    )
    device_config_dev.write_config()

    resp = client.get("/")
    assert resp.status_code == 200
    # Now-showing metadata is rendered by the hero-strip (#heroNowValue /
    # #heroNowMeta) since the redundant dashboard-aside block was removed
    # to match the handoff design. The contract is: plugin display name,
    # custom instance label, and playlist must all appear in the HTML.
    assert b'id="heroNowValue"' in resp.data
    assert b"Weather" in resp.data or b"weather" in resp.data
    assert b"Home Weather" in resp.data
    assert b"Default" in resp.data
    assert b"NOW PLAYING" in resp.data
    assert b'class="now-card ' in resp.data
    assert b"refreshed" in resp.data
    assert b'data-page-shell="dashboard"' in resp.data


def test_dashboard_refresh_cell_renders_forward_eta(
    client, device_config_dev, monkeypatch
):
    monkeypatch.setattr(
        "blueprints.main._current_dt",
        lambda _device_config: datetime(2025, 1, 1, 7, 57, tzinfo=UTC),
        raising=True,
    )
    device_config_dev.refresh_info = RefreshInfo(
        refresh_type="Playlist",
        plugin_id="clock",
        refresh_time="2025-01-01T07:55:00+00:00",
        image_hash=123,
        playlist="Default",
        plugin_instance="Clock A",
    )
    device_config_dev.write_config()

    resp = client.get("/")
    html = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert 'id="heroRefreshValue"' in html
    assert "in 3m" in html
    assert "ETA 8:00 AM" in html


def test_dashboard_plugin_cards_have_valid_hrefs(client, device_config_dev):
    """JTN-214: Plugin cards must render with valid href attributes."""
    resp = client.get("/")
    assert resp.status_code == 200
    # Each plugin should have a link to its plugin page
    # The test client's config should have at least one plugin registered.
    # The card class is `plugin-item` (optionally with additional modifier
    # classes like `plugin-tile` from the tile-based redesign).
    assert b'class="plugin-item' in resp.data
    assert b'href="/plugin/' in resp.data


def test_dashboard_plugin_catalog_exposes_library_link(client):
    resp = client.get("/")
    html = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert 'id="todayKpiSub"' in html
    assert "Plugins" in html
    assert 'href="/plugins"' in html
    assert "Open library" in html


def test_plugin_page_accessible_from_dashboard_links(client, device_config_dev):
    """JTN-214: Links from dashboard plugin cards should serve plugin pages."""
    import re

    resp = client.get("/")
    assert resp.status_code == 200
    # Extract plugin hrefs from the response
    hrefs = re.findall(rb'href="(/plugin/[^"]+)"', resp.data)
    assert len(hrefs) > 0, "Dashboard should have at least one plugin link"
    for href in hrefs:
        plugin_resp = client.get(href.decode())
        assert (
            plugin_resp.status_code == 200
        ), f"Plugin page {href.decode()} should be accessible"


def test_plugins_page_lists_plugin_cards_and_marks_sidebar_active(client):
    resp = client.get("/plugins")
    html = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert 'data-page-shell="plugins"' in html
    assert 'href="/plugin/' in html
    # The previous assertions (`href="/plugins"`, `class="nav-item active"`,
    # `aria-current="page"`) could each be satisfied by unrelated anchors on
    # the page — e.g. any other active sidebar entry would match. Scope the
    # check to the exact `/plugins` anchor in the sidebar nav so we verify
    # that *this specific link* is marked active. The regex tolerates
    # attribute ordering (href-first vs class-first).
    sidebar_active_match = re.search(
        r'<a\s+href="/plugins"[^>]*\bclass="nav-item active"[^>]*\baria-current="page"',
        html,
    ) or re.search(
        r'<a\s+href="/plugins"[^>]*\baria-current="page"[^>]*\bclass="nav-item active"',
        html,
    )
    assert sidebar_active_match, (
        'expected /plugins sidebar anchor to carry both `class="nav-item active"` '
        'and `aria-current="page"`'
    )


def test_shell_marks_sidebar_active_on_management_pages(client):
    cases = [
        ("/playlist", "/playlist"),
        ("/history", "/history"),
        ("/settings", "/settings"),
        ("/settings/api-keys", "/settings/api-keys"),
        ("/api-keys", "/settings/api-keys"),
    ]

    for path, active_href in cases:
        resp = client.get(path)
        html = resp.get_data(as_text=True)
        assert resp.status_code == 200
        active_link = re.search(
            rf'href="{re.escape(active_href)}"[^>]*class="nav-item active"'
            rf'|class="nav-item active"[^>]*href="{re.escape(active_href)}"',
            html,
        )
        assert (
            active_link
        ), f"Expected sidebar link {active_href} to be active on {path}"


def test_next_up_endpoint_and_ssr(client, device_config_dev):
    # Seed playlist with two items so peek returns the second when index is None (first is candidate)
    pm = device_config_dev.get_playlist_manager()
    pm.add_playlist("Default", "00:00", "24:00")
    pl = pm.get_playlist("Default")
    pl.add_plugin(
        {
            "plugin_id": "weather",
            "name": "Home Weather",
            "plugin_settings": {},
            "refresh": {"interval": 600},
        }
    )
    pl.add_plugin(
        {
            "plugin_id": "clock",
            "name": "Clock",
            "plugin_settings": {},
            "refresh": {"interval": 600},
        }
    )
    device_config_dev.write_config()

    # SSR should include the next-up entry in the hero-strip. With the
    # redundant "Next up:" aside removed, the contract is that the hero
    # cell renders the seeded plugin display name.
    resp = client.get("/")
    assert resp.status_code == 200
    assert b'id="heroNextValue"' in resp.data
    assert b"weather" in resp.data or b"clock" in resp.data

    # Endpoint should return a structured JSON
    r = client.get("/next-up")
    assert r.status_code == 200
    data = r.get_json()
    assert isinstance(data, dict)
    # One of the seeded plugin ids
    assert data.get("plugin_id") in ("weather", "clock")


# JTN-213: Dashboard detail panel empty state when preview image exists


def test_dashboard_shows_unavailable_message_when_preview_exists_but_no_plugin_id(
    client, device_config_dev
):
    """When a preview image exists but refresh_info has no plugin_id, show 'Last display info unavailable.'"""
    from PIL import Image

    # Write a dummy processed image so has_preview=True
    img = Image.new("RGB", (10, 10), "black")
    img.save(device_config_dev.processed_image_file)

    # Explicitly ensure refresh_info has no plugin_id
    ri = device_config_dev.get_refresh_info()
    ri.plugin_id = None
    device_config_dev.config["refresh_info"] = ri.to_dict()
    device_config_dev.write_config()

    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Last display info unavailable." in resp.data
    assert b"Display a plugin to see details here." not in resp.data


def test_dashboard_shows_generic_message_when_no_preview_and_no_plugin_id(
    client, device_config_dev
):
    """When no preview image and no plugin_id, show the generic 'Display a plugin' empty state."""
    import os

    # Remove any preview images so has_preview=False
    for path in (
        device_config_dev.processed_image_file,
        device_config_dev.current_image_file,
    ):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass

    # Explicitly ensure refresh_info has no plugin_id
    ri = device_config_dev.get_refresh_info()
    ri.plugin_id = None
    device_config_dev.config["refresh_info"] = ri.to_dict()
    device_config_dev.write_config()

    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Display a plugin to see details here." in resp.data
    assert b"Last display info unavailable." not in resp.data


# ---------------------------------------------------------------------------
# JTN-618 / JTN-619 / JTN-620 — friendly plugin-instance display names
# ---------------------------------------------------------------------------


def test_home_hides_auto_generated_instance_suffix(client, device_config_dev):
    """JTN-618: The NOW SHOWING panel must not expose raw {plugin_id}_saved_settings keys."""
    device_config_dev.refresh_info = RefreshInfo(
        refresh_type="Playlist",
        plugin_id="weather",
        refresh_time="2025-01-01T00:00:00",
        image_hash=123,
        playlist="Default",
        plugin_instance="weather_saved_settings",
    )
    device_config_dev.write_config()

    resp = client.get("/")
    assert resp.status_code == 200
    # The auto-generated internal key must not leak into the rendered HTML.
    assert b"weather_saved_settings" not in resp.data
    # Hero-strip still surfaces the plugin display name.
    assert b'id="heroNowValue"' in resp.data


def test_home_preserves_user_supplied_instance_name(client, device_config_dev):
    """A user-renamed instance should still render in the parenthesised suffix."""
    device_config_dev.refresh_info = RefreshInfo(
        refresh_type="Playlist",
        plugin_id="weather",
        refresh_time="2025-01-01T00:00:00",
        image_hash=123,
        playlist="Default",
        plugin_instance="Morning Weather",
    )
    device_config_dev.write_config()

    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Morning Weather" in resp.data


def test_refresh_info_endpoint_annotates_labels(client, device_config_dev):
    """JTN-618: /refresh-info must expose a friendly label and auto flag to JS."""
    device_config_dev.refresh_info = RefreshInfo(
        refresh_type="Playlist",
        plugin_id="weather",
        refresh_time="2025-01-01T00:00:00",
        image_hash=123,
        playlist="Default",
        plugin_instance="weather_saved_settings",
    )
    device_config_dev.write_config()

    resp = client.get("/refresh-info")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["plugin_id"] == "weather"
    assert payload["plugin_instance_is_auto"] is True
    # Friendly label should not expose the raw key.
    assert "saved_settings" not in payload["plugin_instance_label"]
    assert payload["plugin_display_name"]


def test_refresh_info_endpoint_includes_next_refresh_schedule(
    client, device_config_dev, monkeypatch
):
    monkeypatch.setattr(
        "blueprints.main._current_dt",
        lambda _device_config: datetime(2025, 1, 1, 7, 57, tzinfo=UTC),
        raising=True,
    )
    device_config_dev.refresh_info = RefreshInfo(
        refresh_type="Playlist",
        plugin_id="clock",
        refresh_time="2025-01-01T07:55:00+00:00",
        image_hash=123,
        playlist="Default",
        plugin_instance="Clock A",
    )
    device_config_dev.write_config()

    resp = client.get("/refresh-info")
    assert resp.status_code == 200

    payload = resp.get_json()
    assert payload["cycle_minutes"] == 5
    assert payload["next_refresh_time"].startswith("2025-01-01T08:00:00")
    assert payload["next_refresh_relative"] == "in 3m"
    assert payload["next_refresh_meta"] == "ETA 8:00 AM · Every 5 min · auto"


def test_next_up_endpoint_annotates_labels(client, device_config_dev):
    """JTN-618: /next-up must also annotate labels for the dashboard."""
    pm = device_config_dev.get_playlist_manager()
    pm.add_playlist("Default", "00:00", "24:00")
    pl = pm.get_playlist("Default")
    pl.add_plugin(
        {
            "plugin_id": "weather",
            "name": "weather_saved_settings",
            "plugin_settings": {},
            "refresh": {"interval": 600},
        }
    )
    device_config_dev.write_config()

    resp = client.get("/next-up")
    assert resp.status_code == 200
    data = resp.get_json()
    if data:
        assert data.get("plugin_instance_is_auto") is True
        assert "saved_settings" not in data.get("plugin_instance_label", "")
