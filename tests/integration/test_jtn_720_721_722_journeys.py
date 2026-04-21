# pyright: reportMissingImports=false
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_UI", "").lower() in ("1", "true"),
    reason="UI interactions skipped by env",
)

from tests.integration.browser_helpers import (  # noqa: E402
    install_direct_manual_update,
    navigate_and_wait,
)


def _playlist_names(page) -> list[str]:
    return page.locator(".playlist-item").evaluate_all(
        "(nodes) => nodes.map((node) => node.dataset.playlistName || '')"
    )


def _plugin_instance_names(page, playlist_name: str | None = None) -> list[str]:
    selector = ".plugin-item"
    if playlist_name:
        selector = f'[data-playlist-name="{playlist_name}"] .plugin-item'
    return page.locator(selector).evaluate_all(
        "(nodes) => nodes.map((node) => node.dataset.instanceName || '')"
    )


def _create_playlist_via_ui(
    page,
    live_server: str,
    *,
    name: str,
    start_time: str = "00:00",
    end_time: str = "23:59",
) -> None:
    navigate_and_wait(page, live_server, "/playlist")
    page.locator("#newPlaylistBtn").click()
    page.locator("#playlistModal").wait_for(state="visible", timeout=5000)
    page.locator("#playlist_name").fill(name)
    page.locator("#start_time").fill(start_time)
    page.locator("#end_time").fill(end_time)
    page.locator("#saveButton").click()
    page.wait_for_url(f"{live_server}/playlist", timeout=10000)
    page.wait_for_timeout(600)


def _add_plugin_via_client(
    client,
    *,
    plugin_id: str,
    playlist: str,
    instance_name: str,
    interval: int = 5,
    plugin_settings: dict | None = None,
):
    payload = {
        "plugin_id": plugin_id,
        "refresh_settings": json.dumps(
            {
                "playlist": playlist,
                "instance_name": instance_name,
                "refreshType": "interval",
                "unit": "minute",
                "interval": interval,
            }
        ),
    }
    if plugin_settings:
        payload.update(plugin_settings)
    response = client.post("/add_plugin", data=payload)
    assert response.status_code == 200, response.get_data(as_text=True)


def test_jtn_720_first_run_setup_add_schedule_refresh_history(
    live_server,
    browser_page,
    client,
    flask_app,
    monkeypatch,
):
    install_direct_manual_update(monkeypatch, flask_app)

    page = browser_page

    navigate_and_wait(page, live_server, "/")
    body_text = page.locator("body").inner_text()
    assert "Current display" in body_text
    # The dashboard renders the Display Next CTA alongside the Refresh action
    # as part of the hero strip. The status-badge floating "Check status"
    # label only appears when /api/diagnostics reports a warning state, which
    # an ok dev environment does not, so assert on a stable CTA instead.
    assert "Display Next" in body_text

    navigate_and_wait(page, live_server, "/playlist")
    assert (
        "No plugin instances in this playlist yet." in page.locator("body").inner_text()
    )

    navigate_and_wait(page, live_server, "/plugin/clock")
    page.locator('button[data-plugin-subtab-target="schedule"]').click()
    page.locator("#scheduleForm").wait_for(state="visible", timeout=5000)
    page.locator("#playlist").select_option("Default")
    page.locator("#instance").fill("First Clock")
    page.locator("#scheduleInterval").fill("5")
    page.locator('button[data-plugin-action="add_to_playlist"]').click()
    page.wait_for_timeout(1000)

    navigate_and_wait(page, live_server, "/playlist")
    assert "First Clock" in page.locator("body").inner_text()

    # Expand card only when the toggle is visible (mobile viewport). On
    # desktop the card body is always expanded and the toggle is hidden.
    toggle = page.locator("[data-playlist-toggle]").first
    if toggle.is_visible():
        toggle.click()
    page.locator(".plugin-display-btn").first.click()
    page.wait_for_timeout(1200)
    page.wait_for_url(f"{live_server}/playlist", timeout=10000)

    navigate_and_wait(page, live_server, "/history")
    body_text = page.locator("body").inner_text()
    assert "No history yet." not in body_text
    assert "Source:" in body_text
    assert "clock" in body_text
    assert "First Clock" in body_text


def _wait_for_plugin_order(device_config_dev, playlist_name, expected, timeout_s=5.0):
    """Poll device_config until the playlist's plugin order matches expected.

    Avoids racing the client-side reorder POST against the reload that follows.
    """
    import time

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        pm = device_config_dev.get_playlist_manager()
        pl = pm.get_playlist(playlist_name)
        if pl is not None and [p.name for p in pl.plugins] == expected:
            return
        time.sleep(0.1)
    pm = device_config_dev.get_playlist_manager()
    pl = pm.get_playlist(playlist_name)
    actual = [p.name for p in pl.plugins] if pl else None
    raise AssertionError(
        f"plugin order never reached {expected} (last observed: {actual})"
    )


def test_jtn_721_playlist_roundtrip_create_add_reorder_delete_persist(
    live_server,
    browser_page,
    client,
    device_config_dev,
):
    page = browser_page

    _create_playlist_via_ui(page, live_server, name="Journey List")

    _add_plugin_via_client(
        client,
        plugin_id="clock",
        playlist="Journey List",
        instance_name="Clock Alpha",
    )
    _add_plugin_via_client(
        client,
        plugin_id="year_progress",
        playlist="Journey List",
        instance_name="Year Beta",
    )
    _add_plugin_via_client(
        client,
        plugin_id="todo_list",
        playlist="Journey List",
        instance_name="Todo Gamma",
        plugin_settings={"title": "Journey"},
    )

    navigate_and_wait(page, live_server, "/playlist")
    journey_toggle = page.locator(
        '[data-playlist-name="Journey List"] [data-playlist-toggle]'
    )
    if journey_toggle.is_visible():
        journey_toggle.click()
    page.wait_for_timeout(300)
    assert _plugin_instance_names(page, "Journey List") == [
        "Clock Alpha",
        "Year Beta",
        "Todo Gamma",
    ]

    first_item = page.locator(".plugin-item").nth(0)
    first_item.focus()
    first_item.press("ArrowDown")
    # Wait for the reorder POST to land on the server before reloading so the
    # reload doesn't race against the client-side save.
    _wait_for_plugin_order(
        device_config_dev,
        "Journey List",
        ["Year Beta", "Clock Alpha", "Todo Gamma"],
    )

    page.reload(wait_until="domcontentloaded")
    page.wait_for_selector("[data-page-shell]", timeout=10000)
    journey_toggle_reload = page.locator(
        '[data-playlist-name="Journey List"] [data-playlist-toggle]'
    )
    if journey_toggle_reload.is_visible():
        journey_toggle_reload.click()
    page.wait_for_timeout(300)
    assert _plugin_instance_names(page, "Journey List") == [
        "Year Beta",
        "Clock Alpha",
        "Todo Gamma",
    ]

    page.locator(".delete-instance-btn").first.click()
    page.locator("#deleteInstanceModal").wait_for(state="visible", timeout=5000)
    page.locator("#confirmDeleteInstanceBtn").click()
    # Wait for the delete to be reflected server-side before reloading.
    _wait_for_plugin_order(
        device_config_dev,
        "Journey List",
        ["Clock Alpha", "Todo Gamma"],
    )

    page.reload(wait_until="domcontentloaded")
    page.wait_for_selector("[data-page-shell]", timeout=10000)
    journey_toggle_final = page.locator(
        '[data-playlist-name="Journey List"] [data-playlist-toggle]'
    )
    if journey_toggle_final.is_visible():
        journey_toggle_final.click()
    page.wait_for_timeout(300)
    assert "Journey List" in _playlist_names(page)
    assert _plugin_instance_names(page, "Journey List") == [
        "Clock Alpha",
        "Todo Gamma",
    ]

    playlist = device_config_dev.get_playlist_manager().get_playlist("Journey List")
    assert playlist is not None
    assert [plugin.name for plugin in playlist.plugins] == ["Clock Alpha", "Todo Gamma"]


def test_jtn_722_api_key_roundtrip_add_edit_delete(
    live_server,
    browser_page,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    env_path = Path(tmp_path) / ".env"
    env_path.write_text("", encoding="utf-8")

    page = browser_page
    navigate_and_wait(page, live_server, "/api-keys")

    page.locator("#addApiKeyBtn").click()
    new_row = page.locator(".apikey-row").last
    new_row.locator(".apikey-key").fill("JOURNEY_KEY")
    new_row.locator(".apikey-value").fill("first-secret")
    page.locator("#saveApiKeysBtn").click()
    page.wait_for_timeout(1600)

    navigate_and_wait(page, live_server, "/api-keys")
    assert page.locator(".apikey-row .apikey-key").first.input_value() == "JOURNEY_KEY"
    assert "JOURNEY_KEY=first-secret" in env_path.read_text(encoding="utf-8")

    page.locator(".apikey-row .apikey-value").first.fill("second-secret")
    page.locator("#saveApiKeysBtn").click()
    page.wait_for_timeout(1600)

    navigate_and_wait(page, live_server, "/api-keys")
    assert "JOURNEY_KEY=second-secret" in env_path.read_text(encoding="utf-8")

    page.once("dialog", lambda dialog: dialog.accept())
    page.locator('.apikey-row .btn-delete[data-api-action="delete-row"]').click()
    page.locator("#saveApiKeysBtn").click()
    page.wait_for_timeout(1600)

    navigate_and_wait(page, live_server, "/api-keys")
    assert page.locator(".apikey-row .apikey-key").count() == 0
    assert "JOURNEY_KEY" not in env_path.read_text(encoding="utf-8")
