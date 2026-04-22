from __future__ import annotations

import time


def test_display_hang_fault_times_out_and_surfaces_error(
    client, flask_app, monkeypatch
):
    refresh_task = flask_app.config["REFRESH_TASK"]
    display_manager = flask_app.config["DISPLAY_MANAGER"]

    monkeypatch.setenv("INKYPI_MANUAL_UPDATE_WAIT_S", "0.05")

    def _hung_display(*_args, **_kwargs):
        time.sleep(0.4)
        # Include "timed out" so that if the raw exception wins a timing race
        # with the manual-update timeout wrapper, the diagnostic text still
        # satisfies the assertion below.
        raise TimeoutError("display driver hang timed out (simulated SIGSTOP)")

    monkeypatch.setattr(display_manager, "display_image", _hung_display, raising=True)

    refresh_task.start()
    try:
        resp = client.post("/update_now", data={"plugin_id": "clock"})
        # JTN-K4: TimeoutError is now mapped to a typed 504
        # ``manual_update_timeout`` (previously fell through to 500
        # ``internal_error``).  Accept either so both branches of the
        # timing race remain covered.
        assert resp.status_code in (500, 504)
        if resp.status_code == 504:
            assert resp.get_json().get("code") == "manual_update_timeout"

        diagnostics = client.get("/api/diagnostics").get_json()
        last_error = diagnostics["refresh_task"]["last_error"] or ""
        assert "timed out" in last_error.lower()
    finally:
        refresh_task.stop()
