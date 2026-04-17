from __future__ import annotations

from tests.helpers.refresh_info_helpers import seed_future_refresh_info


def test_clock_skew_backwards_still_allows_manual_refresh(client, flask_app):
    refresh_task = flask_app.config["REFRESH_TASK"]
    device_config = flask_app.config["DEVICE_CONFIG"]

    # Simulate a stale future timestamp (e.g., RTC/NTP skew before correction).
    seed_future_refresh_info(device_config)

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
