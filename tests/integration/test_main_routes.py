# pyright: reportMissingImports=false
import json
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient
from PIL import Image

from model import RefreshInfo


def test_main_page(client: FlaskClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"/preview" in resp.data
    # The dashboard's forms send this token with every state-changing request.
    assert b'<meta name="csrf-token" content="' in resp.data


def test_dashboard_header_actions_use_compact_handoff_button_pattern(
    client: FlaskClient,
) -> None:
    resp = client.get("/")
    html = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert 'id="dashboardRefreshBtn"' in html
    assert 'id="displayNextBtn"' in html
    assert 'class="header-button is-secondary dashboard-header-button"' in html
    assert 'class="header-button primary dashboard-header-button"' in html
    assert 'class="action-button is-secondary dashboard-header-button"' not in html
    assert 'class="action-button primary dashboard-header-button"' not in html


def test_preview_size_mode_native_on_home(
    client: FlaskClient, device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # native: expect native sizing metadata present for controller-driven preview sizing
    device_config_dev.update_value("preview_size_mode", "native", write=True)
    resp = client.get("/")
    assert resp.status_code == 200
    assert b'data-native-width="' in resp.data and b'data-native-height="' in resp.data
    assert b'id="dashboardStageCopy"' in resp.data


def test_preview_size_mode_fit_on_home(
    client: FlaskClient, device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # fit: expect no explicit inline width/height style and still retain metadata
    device_config_dev.update_value("preview_size_mode", "fit", write=True)
    resp = client.get("/")
    assert resp.status_code == 200
    assert b'id="previewImage" style=' not in resp.data
    assert b'data-native-width="' in resp.data


def test_preview_404_when_no_image(client: FlaskClient) -> None:
    dc = client.application.config["DEVICE_CONFIG"]
    for path in (dc.processed_image_file, dc.current_image_file):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
    resp = client.get("/preview")
    assert resp.status_code == 404


def test_preview_serves_current_image_when_exists(
    client: FlaskClient, device_config_dev: Any
) -> None:
    # Write a dummy current image
    from PIL import Image

    img = Image.new("RGB", (10, 10), "black")
    img.save(device_config_dev.current_image_file)

    resp = client.get("/preview")
    assert resp.status_code == 200
    assert resp.mimetype == "image/png"


def test_preview_prefers_processed_over_current(
    client: FlaskClient, device_config_dev: Any
) -> None:
    from PIL import Image

    # Create different colored images to differentiate
    cur = Image.new("RGB", (10, 10), "black")
    cur.save(device_config_dev.current_image_file)
    proc = Image.new("RGB", (10, 10), "white")
    proc.save(device_config_dev.processed_image_file)

    resp = client.get("/preview")
    assert resp.status_code == 200
    assert resp.mimetype == "image/png"


def test_home_now_showing_renders_from_refresh_info(
    client: FlaskClient, device_config_dev: Any
) -> None:
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
    client: FlaskClient, device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "blueprints.main.now_device_tz",
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


def test_dashboard_plugin_cards_have_valid_hrefs(
    client: FlaskClient, device_config_dev: Any
) -> None:
    """JTN-214: Plugin cards must render with valid href attributes."""
    resp = client.get("/")
    assert resp.status_code == 200
    # Each plugin should have a link to its plugin page
    # The test client's config should have at least one plugin registered.
    # The card class is `plugin-item` (optionally with additional modifier
    # classes like `plugin-tile` from the tile-based redesign).
    assert b'class="plugin-item' in resp.data
    assert b'href="/plugin/' in resp.data


def test_dashboard_plugin_catalog_exposes_library_link(client: FlaskClient) -> None:
    resp = client.get("/")
    html = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert 'id="todayKpiSub"' in html
    assert "Plugins" in html
    assert 'href="/plugins"' in html
    assert "Open library" in html


def test_plugin_page_accessible_from_dashboard_links(
    client: FlaskClient, device_config_dev: Any
) -> None:
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


def test_plugins_page_lists_plugin_cards_and_marks_sidebar_active(
    client: FlaskClient,
) -> None:
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


def test_shell_marks_sidebar_active_on_management_pages(client: FlaskClient) -> None:
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


def test_next_up_endpoint_and_ssr(client: FlaskClient, device_config_dev: Any) -> None:
    # Seed playlist with two items so peek returns the second when index is None (first is candidate) -> None -> None
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
    html = resp.get_data(as_text=True)
    assert 'id="heroNextValue">Weather</div>' in html
    assert 'id="heroNextMeta">Playlist: Default</div>' in html

    # Nothing has been shown yet, so the first instance is next.
    r = client.get("/next-up")
    assert r.status_code == 200
    data = r.get_json()
    assert data["playlist"] == "Default"
    assert data["plugin_id"] == "weather"
    assert data["plugin_instance"] == "Home Weather"


def _seed_paused_middle(device_config_dev: Any, paused_at: str) -> None:
    pm = device_config_dev.get_playlist_manager()
    pm.add_playlist("Default", "00:00", "24:00")
    pl = pm.get_playlist("Default")
    for pid, name in (("clock", "Clock"), ("weather", "Weather"), ("rss", "News")):
        pl.add_plugin(
            {
                "plugin_id": pid,
                "name": name,
                "plugin_settings": {},
                "refresh": {"interval": 600},
            }
        )
    pl.current_plugin_index = 0
    paused = pl.find_plugin("weather", "Weather")
    assert paused is not None
    paused.paused = True
    paused.paused_at = paused_at
    device_config_dev.write_config()


def test_next_up_skips_a_resting_paused_instance(
    client: FlaskClient, device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B4: "Next up" must match the scheduler, which passes over a paused
    instance until its retry probe is due, and must not move the index."""
    monkeypatch.setenv("PLUGIN_PAUSE_COOLDOWN_SECONDS", "3600")
    _seed_paused_middle(device_config_dev, datetime.now(UTC).isoformat())

    data = client.get("/next-up").get_json()
    assert data["plugin_id"] == "rss"
    pl = device_config_dev.get_playlist_manager().get_playlist("Default")
    assert pl.current_plugin_index == 0


def test_next_up_shows_a_paused_instance_whose_probe_is_due(
    client: FlaskClient, device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PLUGIN_PAUSE_COOLDOWN_SECONDS", "60")
    old = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    _seed_paused_middle(device_config_dev, old)

    data = client.get("/next-up").get_json()
    assert data["plugin_id"] == "weather"


# JTN-213: Dashboard detail panel empty state when preview image exists


def test_dashboard_shows_unavailable_message_when_preview_exists_but_no_plugin_id(
    client: FlaskClient, device_config_dev: Any
) -> None:
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
    client: FlaskClient, device_config_dev: Any
) -> None:
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


def test_home_hides_auto_generated_instance_suffix(
    client: FlaskClient, device_config_dev: Any
) -> None:
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


def test_home_preserves_user_supplied_instance_name(
    client: FlaskClient, device_config_dev: Any
) -> None:
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


def test_refresh_info_endpoint_annotates_labels(
    client: FlaskClient, device_config_dev: Any
) -> None:
    """JTN-618: /refresh-info must expose a friendly label and auto flag to JS."""
    # rss's display name ("RSS Feed") differs from its humanised id ("Rss"),
    # so these checks fail if the display-name lookup falls back to the id.
    device_config_dev.refresh_info = RefreshInfo(
        refresh_type="Playlist",
        plugin_id="rss",
        refresh_time="2025-01-01T00:00:00",
        image_hash=123,
        playlist="Default",
        plugin_instance="rss_saved_settings",
    )
    device_config_dev.write_config()

    resp = client.get("/refresh-info")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["plugin_id"] == "rss"
    assert payload["plugin_display_name"] == "RSS Feed"
    # An auto-generated instance key is shown as the plugin's display name.
    assert payload["plugin_instance_label"] == "RSS Feed"
    assert payload["plugin_instance_is_auto"] is True


def test_refresh_info_keeps_a_user_named_instance_label(
    client: FlaskClient, device_config_dev: Any
) -> None:
    device_config_dev.refresh_info = RefreshInfo(
        refresh_type="Playlist",
        plugin_id="rss",
        refresh_time="2025-01-01T00:00:00",
        image_hash=123,
        playlist="Default",
        plugin_instance="Morning headlines",
    )
    device_config_dev.write_config()

    payload = client.get("/refresh-info").get_json()
    assert payload["plugin_display_name"] == "RSS Feed"
    assert payload["plugin_instance_label"] == "Morning headlines"
    assert payload["plugin_instance_is_auto"] is False


def test_refresh_info_is_empty_when_it_cannot_be_read(
    client: FlaskClient, device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The dashboard treats {} as "no refresh yet"; partial data would not be."""

    def broken() -> RefreshInfo:
        raise RuntimeError("refresh info unreadable")

    monkeypatch.setattr(device_config_dev, "get_refresh_info", broken)
    resp = client.get("/refresh-info")
    assert resp.status_code == 200
    assert resp.get_json() == {}


def test_refresh_info_endpoint_includes_next_refresh_schedule(
    client: FlaskClient, device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "blueprints.main.now_device_tz",
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


def test_next_up_endpoint_annotates_labels(
    client: FlaskClient, device_config_dev: Any
) -> None:
    """JTN-618: /next-up must also annotate labels for the dashboard."""
    pm = device_config_dev.get_playlist_manager()
    pm.add_playlist("Default", "00:00", "24:00")
    pl = pm.get_playlist("Default")
    pl.add_plugin(
        {
            "plugin_id": "rss",
            "name": "rss_saved_settings",
            "plugin_settings": {},
            "refresh": {"interval": 600},
        }
    )
    device_config_dev.write_config()

    resp = client.get("/next-up")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["plugin_id"] == "rss"
    assert data["plugin_instance"] == "rss_saved_settings"
    assert data["plugin_display_name"] == "RSS Feed"
    assert data["plugin_instance_label"] == "RSS Feed"
    assert data["plugin_instance_is_auto"] is True


def test_next_up_is_empty_without_an_active_playlist(
    client: FlaskClient, device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    pm = device_config_dev.get_playlist_manager()
    monkeypatch.setattr(pm, "determine_active_playlist", lambda _dt: None)

    resp = client.get("/next-up")
    assert resp.status_code == 200
    assert resp.get_json() == {}


def test_next_up_is_empty_when_the_playlist_has_nothing_to_show(
    client: FlaskClient,
) -> None:
    # The dev config's Default playlist starts with no plugins.
    resp = client.get("/next-up")
    assert resp.status_code == 200
    assert resp.get_json() == {}


def test_next_up_is_empty_when_the_playlist_lookup_fails(
    client: FlaskClient, device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    pm = device_config_dev.get_playlist_manager()

    def broken(_current_dt: datetime) -> None:
        raise RuntimeError("playlist config unreadable")

    monkeypatch.setattr(pm, "determine_active_playlist", broken)
    resp = client.get("/next-up")
    assert resp.status_code == 200
    assert resp.get_json() == {}


# ---- /api/current_image: the dashboard polls it with If-Modified-Since ----

# 2023-11-14 22:13:20 UTC, a whole second, as HTTP dates have no fractions.
_IMAGE_MTIME = 1_700_000_000
_IMAGE_MTIME_HTTP = "Tue, 14 Nov 2023 22:13:20 GMT"


def _write_current_image(device_config_dev: Any) -> bytes:
    path = Path(device_config_dev.current_image_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), "white").save(path)
    os.utime(path, (_IMAGE_MTIME, _IMAGE_MTIME))
    return path.read_bytes()


def test_current_image_is_served_with_its_cache_validators(
    client: FlaskClient, device_config_dev: Any
) -> None:
    image = _write_current_image(device_config_dev)
    name = Path(device_config_dev.current_image_file).name

    resp = client.get("/api/current_image")
    assert resp.status_code == 200
    assert resp.data == image
    assert resp.mimetype == "image/png"
    assert resp.headers["Last-Modified"] == _IMAGE_MTIME_HTTP
    assert resp.headers["Cache-Control"] == "no-cache"
    assert resp.headers["Content-Disposition"] == f'inline; filename="{name}"'


def test_current_image_revalidation_with_last_modified_returns_304(
    client: FlaskClient, device_config_dev: Any
) -> None:
    """The browser sends Last-Modified back; an unchanged image is not resent."""
    _write_current_image(device_config_dev)
    last_modified = client.get("/api/current_image").headers["Last-Modified"]

    resp = client.get(
        "/api/current_image", headers={"If-Modified-Since": last_modified}
    )
    assert resp.status_code == 304
    assert resp.data == b""


def test_current_image_changed_since_the_client_copy_is_resent(
    client: FlaskClient, device_config_dev: Any
) -> None:
    image = _write_current_image(device_config_dev)
    one_second_older = "Tue, 14 Nov 2023 22:13:19 GMT"

    resp = client.get(
        "/api/current_image", headers={"If-Modified-Since": one_second_older}
    )
    assert resp.status_code == 200
    assert resp.data == image


def test_current_image_ignores_an_unreadable_if_modified_since(
    client: FlaskClient, device_config_dev: Any
) -> None:
    image = _write_current_image(device_config_dev)

    resp = client.get(
        "/api/current_image", headers={"If-Modified-Since": "invalid-date-format"}
    )
    assert resp.status_code == 200
    assert resp.data == image


def test_current_image_missing_is_a_json_404(
    client: FlaskClient, device_config_dev: Any
) -> None:
    Path(device_config_dev.current_image_file).unlink(missing_ok=True)

    resp = client.get("/api/current_image")
    assert resp.status_code == 404
    body = resp.get_json()
    assert body["success"] is False
    assert body["error"] == "Image not found"


# ---- /dev/mock-frame ----


def _write_mock_frame(flask_app: Flask) -> bytes:
    frame_path = Path(flask_app.config["DISPLAY_MANAGER"].display.mock_frame_path)
    frame_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), "black").save(frame_path)
    return frame_path.read_bytes()


def test_dev_mock_frame_serves_the_frame_in_dev_mode(
    client: FlaskClient, flask_app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INKYPI_ENV", "dev")
    frame = _write_mock_frame(flask_app)

    resp = client.get("/dev/mock-frame")
    assert resp.status_code == 200
    assert resp.mimetype == "image/png"
    assert resp.data == frame


def test_dev_mock_frame_is_hidden_outside_dev_mode(
    client: FlaskClient, flask_app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INKYPI_ENV", "production")
    _write_mock_frame(flask_app)

    assert client.get("/dev/mock-frame").status_code == 404


def test_dev_mock_frame_404_before_the_first_frame(
    client: FlaskClient, flask_app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INKYPI_ENV", "dev")
    frame_path = Path(flask_app.config["DISPLAY_MANAGER"].display.mock_frame_path)
    frame_path.unlink(missing_ok=True)

    assert client.get("/dev/mock-frame").status_code == 404


# ---- /static/<path> ----


def test_static_route_serves_a_script_and_404s_a_missing_file(
    client: FlaskClient,
) -> None:
    script = Path(__file__).resolve().parents[2] / "src/static/scripts/csrf.js"
    resp = client.get("/static/scripts/csrf.js")
    assert resp.status_code == 200
    assert resp.data == script.read_bytes()

    assert client.get("/static/scripts/no-such-file.js").status_code == 404


# ---- /api/plugin_order: dashboard drag-and-drop ----


def _plugin_ids(device_config_dev: Any) -> list[str]:
    return [p["id"] for p in device_config_dev.get_plugins()]


def test_plugin_order_is_saved_and_applied(
    client: FlaskClient, device_config_dev: Any
) -> None:
    order = list(reversed(_plugin_ids(device_config_dev)))
    assert len(order) > 1, "the dev config registers no plugins to reorder"

    resp = client.post("/api/plugin_order", json={"order": order})
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True
    assert _plugin_ids(device_config_dev) == order
    saved = json.loads(Path(device_config_dev.config_file).read_text())
    assert saved["plugin_order"] == order


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        pytest.param(["clock", "weather"], "Invalid", id="not-an-object"),
        pytest.param({"order": "clock"}, None, id="order-not-a-list"),
        pytest.param({"order": [123]}, "strings", id="non-string-ids"),
        pytest.param({"order": []}, "include every plugin ID exactly once", id="empty"),
        pytest.param(
            {"order": ["nonexistent_plugin_id_xyz"]},
            "unknown plugin IDs",
            id="unknown-id",
        ),
    ],
)
def test_plugin_order_rejects_a_bad_order_and_keeps_the_old_one(
    client: FlaskClient, device_config_dev: Any, payload: Any, error: str | None
) -> None:
    before = _plugin_ids(device_config_dev)

    resp = client.post("/api/plugin_order", json=payload)
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["success"] is False
    if error is not None:
        assert error.lower() in body["error"].lower()
    # User-supplied ids are never echoed back (py/reflective-xss).
    assert "nonexistent_plugin_id_xyz" not in body["error"]
    assert _plugin_ids(device_config_dev) == before


def test_plugin_order_rejects_duplicates_and_omissions(
    client: FlaskClient, device_config_dev: Any
) -> None:
    ids = _plugin_ids(device_config_dev)

    duplicate = client.post("/api/plugin_order", json={"order": [ids[0], ids[0]]})
    assert duplicate.status_code == 400
    assert "duplicate" in duplicate.get_json()["error"].lower()

    partial = client.post("/api/plugin_order", json={"order": [ids[0]]})
    assert partial.status_code == 400
    assert "exactly once" in partial.get_json()["error"]
    assert _plugin_ids(device_config_dev) == ids


def test_plugin_order_rejects_malformed_json(client: FlaskClient) -> None:
    resp = client.post(
        "/api/plugin_order", data="not json", content_type="application/json"
    )
    assert resp.status_code == 400
    assert resp.get_json()["success"] is False


def test_plugin_order_never_reflects_markup(client: FlaskClient) -> None:
    """Regression for CodeQL py/reflective-xss: ids are not echoed back."""
    for payload in (
        "<script>alert(1)</script>",
        '"><img src=x onerror=alert(1)>',
        "<svg/onload=alert(1)>",
        "javascript:alert(1)",
    ):
        resp = client.post("/api/plugin_order", json={"order": [payload]})
        assert resp.status_code == 400
        assert payload not in resp.get_data(as_text=True)
        assert resp.headers["Content-Type"].startswith("application/json")
