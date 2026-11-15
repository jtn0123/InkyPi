from __future__ import annotations

import time
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient


def test_display_hang_fault_times_out_and_surfaces_error(
    client: FlaskClient, flask_app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    refresh_task = flask_app.config["REFRESH_TASK"]
    display_manager = flask_app.config["DISPLAY_MANAGER"]

    # The loop takes the request at once (nothing else is due), so the wait
    # for it to start passes and the wait for the image runs out mid-hang.
    monkeypatch.setenv("INKYPI_MANUAL_UPDATE_WAIT_S", "0.2")

    def _hung_display(*_args: Any, **_kwargs: Any) -> None:
        time.sleep(0.6)
        # Include "timed out" so that if the raw exception wins a timing race
        # with the manual-update timeout wrapper, the diagnostic text still
        # satisfies the assertion below.
        raise TimeoutError("display driver hang timed out (simulated SIGSTOP)")

    monkeypatch.setattr(display_manager, "display_image", _hung_display, raising=True)

    refresh_task.start()
    try:
        resp = client.post("/update_now", data={"plugin_id": "clock"})
        # JTN-K4: whichever wins the timing race, the route sees a
        # TimeoutError: the manual-update wait expiring, or the display's own
        # TimeoutError re-raised from the finished request. Both map to the
        # typed 504.
        assert resp.status_code == 504
        assert resp.get_json().get("code") == "manual_update_timeout"

        # The caller giving up records nothing. Once the hung display gives
        # up too, diagnostics shows the display's own error.
        last_error = ""
        deadline = time.monotonic() + 5
        while not last_error and time.monotonic() < deadline:
            diagnostics = client.get("/api/diagnostics").get_json()
            last_error = diagnostics["refresh_task"]["last_error"] or ""
            time.sleep(0.05)
        assert "display driver hang" in last_error
    finally:
        refresh_task.stop()
