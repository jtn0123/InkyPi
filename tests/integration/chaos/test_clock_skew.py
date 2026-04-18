from __future__ import annotations

from tests.helpers.refresh_info_helpers import seed_future_refresh_info


def test_clock_skew_backwards_still_allows_manual_refresh(client, flask_app):
    refresh_task = flask_app.config["REFRESH_TASK"]
    device_config = flask_app.config["DEVICE_CONFIG"]

    # Simulate a stale future timestamp (e.g., RTC/NTP skew before correction).
    # Mutate both ``device_config.refresh_info`` (read by diagnostics) AND the
    # clock PluginInstance's ``latest_refresh_time`` (read by
    # ``PluginInstance.should_refresh`` inside ``PlaylistRefresh.execute``),
    # otherwise the refresh path skips the future-timestamp branch entirely
    # and the regression would pass without exercising the intended code.
    original_refresh_info = device_config.refresh_info
    playlist = device_config.get_playlist_manager().get_playlist("Default")
    clock_plugin = None
    original_latest_refresh_time = None
    if playlist is not None:
        for plugin in playlist.plugins:
            if plugin.plugin_id == "clock":
                clock_plugin = plugin
                original_latest_refresh_time = plugin.latest_refresh_time
                break

    future_ts = seed_future_refresh_info(device_config)
    if clock_plugin is not None:
        clock_plugin.latest_refresh_time = future_ts

    refresh_task.start()
    try:
        resp = client.post("/update_now", data={"plugin_id": "clock"})
        assert resp.status_code == 200

        diag_resp = client.get("/api/diagnostics")
        assert diag_resp.status_code == 200
        diagnostics = diag_resp.get_json()
        assert diagnostics["refresh_task"]["last_error"] is None
    finally:
        refresh_task.stop()
        device_config.refresh_info = original_refresh_info
        if clock_plugin is not None:
            clock_plugin.latest_refresh_time = original_latest_refresh_time
