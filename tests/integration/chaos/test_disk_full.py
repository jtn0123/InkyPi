from __future__ import annotations


def test_disk_full_fault_surfaces_through_diagnostics(client, flask_app, monkeypatch):
    refresh_task = flask_app.config["REFRESH_TASK"]
    display_manager = flask_app.config["DISPLAY_MANAGER"]

    def _raise_disk_full(*_args, **_kwargs):
        raise OSError("disk full while writing display artifacts")

    monkeypatch.setattr(
        display_manager, "display_image", _raise_disk_full, raising=True
    )

    refresh_task.start()
    try:
        resp = client.post("/update_now", data={"plugin_id": "clock"})
        assert resp.status_code == 500

        diagnostics = client.get("/api/diagnostics").get_json()
        last_error = diagnostics["refresh_task"]["last_error"] or ""
        assert "disk full" in last_error.lower()
    finally:
        refresh_task.stop()
