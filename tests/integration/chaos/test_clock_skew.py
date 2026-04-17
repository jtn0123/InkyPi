from __future__ import annotations

from datetime import UTC, datetime, timedelta


def test_clock_skew_backwards_still_allows_manual_refresh(client, flask_app):
    # Lazy import keeps the production `model` dependency contained inside the
    # test body (Sonar pythonarchitecture:S7788), matching the pattern used by
    # the shared browser_helpers layer.
    from model import RefreshInfo

    refresh_task = flask_app.config["REFRESH_TASK"]
    device_config = flask_app.config["DEVICE_CONFIG"]

    # Simulate a stale future timestamp (e.g., RTC/NTP skew before correction).
    future_ts = (datetime.now(UTC) + timedelta(days=90)).isoformat()
    device_config.refresh_info = RefreshInfo(
        refresh_type="Playlist",
        plugin_id="clock",
        refresh_time=future_ts,
        image_hash="future-hash",
        playlist="Default",
        plugin_instance="Clock",
    )

    refresh_task.start()
    try:
        resp = client.post("/update_now", data={"plugin_id": "clock"})
        assert resp.status_code == 200

        diagnostics = client.get("/api/diagnostics").get_json()
        assert diagnostics["refresh_task"]["last_error"] is None
    finally:
        refresh_task.stop()
