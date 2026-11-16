"""History v2 design tests: day grouping, source filter, lightbox, refresh.

Covers the polish-and-improve handoff (History v2.dc.html):
- Day-grouped grid with Today/Yesterday headers and per-day render counts
- All/Playlist/Manual source filter toolbar with a live shown count
- Render-preview lightbox with Display / Download / Delete actions
- Refresh button with a leading spin icon
- Exact-ratio thumbnails driven by the panel resolution
"""

import json
import os
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from PIL import Image


def _clear_history(d: str) -> None:
    os.makedirs(d, exist_ok=True)
    for f in os.listdir(d):
        os.remove(os.path.join(d, f))


def _save_png(d: str, name: str, mtime: float | None = None) -> str:
    path = os.path.join(d, name)
    Image.new("RGB", (10, 10), "white").save(path)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


# ---------------------------------------------------------------------------
# Day grouping
# ---------------------------------------------------------------------------


def test_history_groups_by_day_with_today_label(
    client: Any, device_config_dev: Any
) -> None:
    d = device_config_dev.history_image_dir
    _clear_history(d)
    _save_png(d, "display_v2_today.png")

    resp = client.get("/history")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "history-group" in body
    assert "history-day-label" in body
    assert ">Today<" in body
    assert "1 render<" in body


def test_history_groups_split_today_and_yesterday(
    client: Any, device_config_dev: Any
) -> None:
    d = device_config_dev.history_image_dir
    _clear_history(d)
    now = time.time()
    _save_png(d, "display_v2_now.png", mtime=now)
    _save_png(d, "display_v2_yday.png", mtime=now - 86400)

    resp = client.get("/history")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert ">Today<" in body
    assert ">Yesterday<" in body
    # Two separate day sections
    assert body.count("history-day-head") == 2


def test_day_label_helper() -> None:
    from services.history import day_label

    now = datetime(2026, 7, 7, 12, 0, tzinfo=UTC)
    assert day_label(now, now) == "Today"
    assert day_label(now - timedelta(days=1), now) == "Yesterday"
    assert day_label(datetime(2026, 7, 1, 8, 0, tzinfo=UTC), now) == "Jul 1, 2026"


def test_group_images_by_day_consecutive_buckets() -> None:
    from services.history import group_by_day

    images = [
        {"date_key": "2026-07-07", "day_label": "Today"},
        {"date_key": "2026-07-07", "day_label": "Today"},
        {"date_key": "2026-07-06", "day_label": "Yesterday"},
    ]
    groups = group_by_day(images)
    assert [g["label"] for g in groups] == ["Today", "Yesterday"]
    assert [len(g["entries"]) for g in groups] == [2, 1]
    assert group_by_day([]) == []


# ---------------------------------------------------------------------------
# Source filter toolbar
# ---------------------------------------------------------------------------


def test_history_filter_toolbar_renders_with_items(
    client: Any, device_config_dev: Any
) -> None:
    d = device_config_dev.history_image_dir
    _clear_history(d)
    _save_png(d, "display_v2_filter.png")

    resp = client.get("/history")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'data-history-filter="all"' in body
    assert 'data-history-filter="playlist"' in body
    assert 'data-history-filter="manual"' in body
    assert 'id="historyShownCount"' in body
    assert 'aria-label="Filter renders by source"' in body
    # No-match empty state ships hidden, ready for the client-side filter
    assert 'id="historyFilterEmpty"' in body
    assert "No renders match this filter." in body


def test_history_filter_toolbar_absent_when_empty(
    client: Any, device_config_dev: Any
) -> None:
    d = device_config_dev.history_image_dir
    _clear_history(d)

    resp = client.get("/history")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "data-history-filter" not in body
    assert "No history yet." in body


def test_history_cards_carry_category_attr(client: Any, device_config_dev: Any) -> None:
    d = device_config_dev.history_image_dir
    _clear_history(d)
    _save_png(d, "display_v2_playlist.png")
    with open(os.path.join(d, "display_v2_playlist.json"), "w", encoding="utf-8") as fh:
        json.dump({"refresh_type": "Playlist", "plugin_id": "weather"}, fh)
    _save_png(d, "display_v2_manual.png")
    with open(os.path.join(d, "display_v2_manual.json"), "w", encoding="utf-8") as fh:
        json.dump({"refresh_type": "Manual Update", "plugin_id": "clock"}, fh)
    _save_png(d, "display_v2_nometa.png")

    resp = client.get("/history")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'data-category="playlist"' in body
    # Manual Update and missing-sidecar entries both count as manual
    assert body.count('data-category="manual"') == 2


# ---------------------------------------------------------------------------
# Render-preview lightbox
# ---------------------------------------------------------------------------


def test_history_lightbox_modal_markup(client: Any, device_config_dev: Any) -> None:
    d = device_config_dev.history_image_dir
    _clear_history(d)
    _save_png(d, "display_v2_lightbox.png")

    resp = client.get("/history")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'id="lightboxModal"' in body
    assert "lightbox-sheet" in body
    assert 'id="lightboxDisplayBtn"' in body
    assert 'id="lightboxDownloadLink"' in body
    assert 'id="lightboxDeleteBtn"' in body
    assert 'id="lightboxSource"' in body
    assert "Render preview" in body


def test_history_thumbs_carry_lightbox_data(
    client: Any, device_config_dev: Any
) -> None:
    d = device_config_dev.history_image_dir
    _clear_history(d)
    fname = "display_v2_thumbdata.png"
    _save_png(d, fname)
    with open(
        os.path.join(d, "display_v2_thumbdata.json"), "w", encoding="utf-8"
    ) as fh:
        json.dump(
            {"refresh_type": "Playlist", "plugin_id": "weather", "playlist": "Daily"},
            fh,
        )

    resp = client.get("/history")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert f'data-lightbox-filename="{fname}"' in body
    assert "data-lightbox-sub=" in body
    assert "data-lightbox-source=" in body
    assert "Playlist • weather • Daily" in body


def test_history_page_no_longer_uses_generic_lightbox(client: Any) -> None:
    resp = client.get("/history")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "scripts/lightbox.js" not in body


# ---------------------------------------------------------------------------
# Refresh button + exact-ratio thumbs
# ---------------------------------------------------------------------------


def test_history_refresh_button_has_icon_and_label(client: Any) -> None:
    resp = client.get("/history")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    idx = body.index('id="historyRefreshBtn"')
    # Wide window: the inline arrows-clockwise SVG is over 600 chars long.
    button_html = body[idx : idx + 2500]
    assert "dashboard-header-button" in body[idx - 200 : idx + 200]
    assert "btn-leading-icon" in button_html
    assert '<span class="button-text">Refresh</span>' in button_html


def test_history_thumb_ratio_matches_panel_resolution(
    client: Any, device_config_dev: Any
) -> None:
    d = device_config_dev.history_image_dir
    _clear_history(d)
    _save_png(d, "display_v2_ratio.png")

    resp = client.get("/history")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # Dev config resolution is 800x480
    assert "--history-thumb-ratio: 800 / 480" in body


# ---------------------------------------------------------------------------
# history_page.js wiring (static contract, mirrors test_history_actions.py)
# ---------------------------------------------------------------------------


def test_history_page_js_defines_filter_and_lightbox(client: Any) -> None:
    resp = client.get("/static/scripts/history_page.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)
    assert "function applyFilter(" in js
    assert "data-history-filter" in js
    assert "function openLightbox(" in js
    assert "lightboxModal" in js
    assert "htmx:afterSettle" in js
    # Refresh spins its leading icon while reloading
    assert 'classList.add("loading")' in js
