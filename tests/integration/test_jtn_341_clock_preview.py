# pyright: reportMissingImports=false
"""Regression tests for JTN-341 — Clock plugin Update Preview silent failure.

Dogfooding on 2026-04-08 showed that clicking "Update Preview" on the Clock
plugin settings page produced a 200 JSON response from ``/update_now`` but the
"Latest from this plugin" card never populated because the image was saved to
the history directory WITHOUT a ``plugin_id`` sidecar key — so
``/plugin_latest_image/clock`` could never find it.

These tests cover:

1. End-to-end: the direct (refresh task not running) update_now code path
   must save a history entry whose sidecar JSON contains the requested
   ``plugin_id``, and ``/plugin_latest_image/<plugin_id>`` must return 200
   with an image.
2. Error handling: when plugin ``generate_image`` raises, the response must
   be a 4xx/5xx with a SAFE user-facing message (no raw ``str(exc)`` leakage)
   and ``logger.exception`` must be called so Sentry/Loki captures it.
3. The fix must also cover JTN-318-style exception exposure in ``plugin.py``.
"""

import json
import logging
import os

# ---------------------------------------------------------------------------
# 1. End-to-end happy path for the clock preview
# ---------------------------------------------------------------------------


def test_clock_update_preview_populates_latest_plugin_image(
    client, monkeypatch, flask_app, device_config_dev
):
    """Clock Update Preview must make /plugin_latest_image/clock serve an image.

    Reproduces JTN-341: previously the direct update_now path called
    display_manager.display_image without ``history_meta``, so the sidecar
    JSON had no ``plugin_id`` and the lookup endpoint always 404'd.
    """
    from display.display_manager import DisplayManager

    # Force the refresh task OFF so we take the _update_now_direct code path
    flask_app.config["REFRESH_TASK"].running = False

    # Use the REAL DisplayManager._save_history_entry so we exercise the sidecar
    # write and the /plugin_latest_image lookup end-to-end.  Stub the actual
    # display driver instead of stubbing display_image.
    dm = flask_app.config["DISPLAY_MANAGER"]
    monkeypatch.setattr(dm.display, "display_image", lambda *a, **kw: None)

    # Ensure the real history dir is empty (test isolation)
    history_dir = device_config_dev.history_image_dir
    os.makedirs(history_dir, exist_ok=True)
    for name in os.listdir(history_dir):
        os.remove(os.path.join(history_dir, name))

    # POST the default Clock settings — this is the same payload the
    # /plugin/clock settings page submits on "Update Preview".
    resp = client.post(
        "/update_now",
        data={
            "plugin_id": "clock",
            "selectedClockFace": "Gradient Clock",
            "primaryColor": "#db3246",
            "secondaryColor": "#000000",
        },
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.json.get("success") is True

    # The sidecar must contain plugin_id so /plugin_latest_image can find it
    json_files = [n for n in os.listdir(history_dir) if n.endswith(".json")]
    assert json_files, "No history sidecar written — JTN-341 regression"

    with open(os.path.join(history_dir, json_files[0]), encoding="utf-8") as fh:
        meta = json.load(fh)
    assert (
        meta.get("plugin_id") == "clock"
    ), f"Sidecar missing plugin_id (JTN-341 regression): {meta}"

    # /plugin_latest_image/clock must now serve the image (no more 404)
    latest = client.get("/plugin_latest_image/clock")
    assert latest.status_code == 200
    assert latest.content_type.startswith("image/")
    assert len(latest.get_data()) > 0

    # Unknown plugin still 404s
    assert client.get("/plugin_latest_image/nonexistent_xyz").status_code == 404

    # Assert DisplayManager was not bypassed
    assert isinstance(dm, DisplayManager)


# ---------------------------------------------------------------------------
# 2. Error handling — plugin RuntimeError surfaces safely to user
# ---------------------------------------------------------------------------


def test_clock_update_preview_runtime_error_returns_400_and_logs(
    client, monkeypatch, flask_app, caplog
):
    """When generate_image raises RuntimeError, we must return a user-facing
    4xx with a safe message AND call logger.exception so the failure is
    captured in logs (JTN-318 pattern).
    """
    from plugins.plugin_registry import get_plugin_instance

    plugin_authored_message = "Failed to display clock."

    def boom(*args, **kwargs):
        raise RuntimeError(plugin_authored_message)

    # Patch both the cached instance (non-dev mode reuses it) and the class.
    clock_inst = get_plugin_instance({"id": "clock", "class": "Clock"})
    monkeypatch.setattr(clock_inst, "generate_image", boom, raising=False)

    flask_app.config["REFRESH_TASK"].running = False

    # Prevent the fallback error-card write from touching the real display
    dm = flask_app.config["DISPLAY_MANAGER"]
    monkeypatch.setattr(dm, "display_image", lambda *a, **kw: None, raising=True)

    with caplog.at_level(logging.ERROR, logger="blueprints.plugin"):
        resp = client.post(
            "/update_now",
            data={"plugin_id": "clock", "selectedClockFace": "Gradient Clock"},
        )

    # Must be a 4xx error, NOT a silent 200 (JTN-341)
    assert resp.status_code == 400
    body = resp.json or {}
    assert body.get("success") is False
    # JTN-326: the plugin RuntimeError message is NO LONGER reflected back to
    # the client (py/stack-trace-exposure).  The response carries a generic
    # message and the real cause is logged server-side.
    assert plugin_authored_message not in body.get("error", "")
    assert body.get("error") == "An internal error occurred"
    assert body.get("code") == "plugin_error"

    # logger.exception (JTN-318): stacktrace must be captured, and any record
    # at ERROR level from blueprints.plugin with exc_info set satisfies this.
    exception_records = [
        rec
        for rec in caplog.records
        if rec.name == "blueprints.plugin"
        and rec.levelno >= logging.ERROR
        and rec.exc_info is not None
    ]
    assert exception_records, (
        "Expected logger.exception call in blueprints.plugin, "
        f"got: {[(r.name, r.levelname, r.message) for r in caplog.records]}"
    )


def test_clock_update_preview_unexpected_exception_returns_500_and_logs(
    client, monkeypatch, flask_app, caplog
):
    """Unexpected (non-RuntimeError) exceptions must return 500 with a
    generic message — never ``str(exc)`` — and must logger.exception.
    """
    from plugins.plugin_registry import get_plugin_instance

    secret_marker = "SECRET_DB_CONNSTRING=postgres://u:p@internal"

    def boom(*args, **kwargs):
        raise ValueError(secret_marker)

    clock_inst = get_plugin_instance({"id": "clock", "class": "Clock"})
    monkeypatch.setattr(clock_inst, "generate_image", boom, raising=False)

    flask_app.config["REFRESH_TASK"].running = False
    dm = flask_app.config["DISPLAY_MANAGER"]
    monkeypatch.setattr(dm, "display_image", lambda *a, **kw: None, raising=True)

    with caplog.at_level(logging.ERROR, logger="blueprints.plugin"):
        resp = client.post(
            "/update_now",
            data={"plugin_id": "clock", "selectedClockFace": "Gradient Clock"},
        )

    assert resp.status_code == 500
    body = resp.json or {}
    assert body.get("success") is False
    # MUST NOT leak the raw exception text
    assert secret_marker not in (body.get("error") or "")
    assert secret_marker not in json.dumps(body)
    assert body.get("code") == "internal_error"

    # Must still logger.exception the failure
    assert any(
        "Unexpected error generating preview" in rec.message for rec in caplog.records
    ), f"Expected logger.exception call, got: {[r.message for r in caplog.records]}"
