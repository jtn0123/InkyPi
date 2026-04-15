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

from tests.integration.browser_helpers import navigate_and_wait  # noqa: E402


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
    display_manager = flask_app.config["DISPLAY_MANAGER"]
    refresh_task = flask_app.config["REFRESH_TASK"]
    device_config = flask_app.config["DEVICE_CONFIG"]
    monkeypatch.setattr(
        display_manager.display,
        "display_image",
        lambda *args, **kwargs: None,
        raising=True,
    )

    def _manual_update_direct(refresh_action):
        from model import RefreshInfo
        from plugins.plugin_registry import get_plugin_instance
        from utils.image_utils import compute_image_hash
        from utils.time_utils import now_device_tz

        plugin_config = device_config.get_plugin(refresh_action.get_plugin_id())
        plugin = get_plugin_instance(plugin_config)
        current_dt = now_device_tz(device_config)
        image = refresh_action.execute(plugin, device_config, current_dt)
        refresh_info = refresh_action.get_refresh_info()
        display_manager.display_image(
            image,
            image_settings=plugin_config.get("image_settings", []),
            history_meta=refresh_info,
        )
        device_config.refresh_info = RefreshInfo(
            refresh_type=refresh_info.get("refresh_type"),
            plugin_id=refresh_info.get("plugin_id"),
            playlist=refresh_info.get("playlist"),
            plugin_instance=refresh_info.get("plugin_instance"),
            refresh_time=current_dt.isoformat(),
            image_hash=compute_image_hash(image),
        )
        device_config.write_config()
        return {"generate_ms": 0}

    monkeypatch.setattr(refresh_task, "manual_update", _manual_update_direct)

    page = browser_page

    navigate_and_wait(page, live_server, "/")
    assert "Preview the current display" in page.locator("body").inner_text()

    navigate_and_wait(page, live_server, "/playlist")
    assert (
        "No plugin instances in this playlist yet." in page.locator("body").inner_text()
    )

    navigate_and_wait(page, live_server, "/plugin/clock")
    page.locator('button[data-open-modal="scheduleModal"]').click()
    page.locator("#scheduleModal").wait_for(state="visible", timeout=5000)
    page.locator("#playlist").select_option("Default")
    page.locator("#instance").fill("First Clock")
    page.locator("#scheduleInterval").fill("5")
    page.locator('button[data-plugin-action="add_to_playlist"]').click()
    page.locator("#scheduleModal").wait_for(state="hidden", timeout=10000)

    navigate_and_wait(page, live_server, "/playlist")
    assert "First Clock" in page.locator("body").inner_text()

    page.locator("[data-playlist-toggle]").first.click()
    page.locator(".plugin-display-btn").first.click()
    page.wait_for_timeout(1200)
    page.wait_for_url(f"{live_server}/playlist", timeout=10000)

    navigate_and_wait(page, live_server, "/history")
    body_text = page.locator("body").inner_text()
    assert "No history yet." not in body_text
    assert "Source:" in body_text
    assert "clock" in body_text
    assert "First Clock" in body_text


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
    page.locator('[data-playlist-name="Journey List"] [data-playlist-toggle]').click()
    page.wait_for_timeout(300)
    assert _plugin_instance_names(page, "Journey List") == [
        "Clock Alpha",
        "Year Beta",
        "Todo Gamma",
    ]

    first_item = page.locator(".plugin-item").nth(0)
    first_item.focus()
    first_item.press("ArrowDown")
    page.wait_for_timeout(800)

    page.reload(wait_until="domcontentloaded")
    page.wait_for_selector("[data-page-shell]", timeout=10000)
    page.locator('[data-playlist-name="Journey List"] [data-playlist-toggle]').click()
    page.wait_for_timeout(300)
    assert _plugin_instance_names(page, "Journey List") == [
        "Year Beta",
        "Clock Alpha",
        "Todo Gamma",
    ]

    page.locator(".delete-instance-btn").first.click()
    page.locator("#deleteInstanceModal").wait_for(state="visible", timeout=5000)
    page.locator("#confirmDeleteInstanceBtn").click()
    page.wait_for_timeout(800)

    page.reload(wait_until="domcontentloaded")
    page.wait_for_selector("[data-page-shell]", timeout=10000)
    page.locator('[data-playlist-name="Journey List"] [data-playlist-toggle]').click()
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
