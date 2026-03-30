"""Update, update-status, and version-check route handlers."""

import time

from flask import current_app, jsonify, request

import blueprints.settings as _mod
from utils.http_utils import json_internal_error


@_mod.settings_bp.route("/settings/update", methods=["POST"])  # start update
def start_update():
    """Trigger InkyPi update via systemd-run when available, with dev fallback.

    Accepts optional JSON body ``{"target_version": "v1.2.0"}`` to update to a
    specific tag.  Returns JSON immediately; progress is visible in the Logs
    panel via /api/logs.
    """
    try:
        with _mod._update_lock:
            if _mod._UPDATE_STATE.get("running"):
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Update already in progress.",
                            "running": True,
                            "unit": _mod._UPDATE_STATE.get("unit"),
                        }
                    ),
                    409,
                )

        # Accept optional target tag from JSON body
        target_tag: str | None = None
        try:
            body = request.get_json(silent=True) or {}
            raw = body.get("target_version")
            if raw and isinstance(raw, str):
                target_tag = raw.strip()
        except Exception:
            pass

        if target_tag and not _mod._TAG_RE.fullmatch(target_tag):
            return (
                jsonify({"success": False, "error": "Invalid target version format"}),
                400,
            )

        script_path = _mod._get_update_script_path()
        unit = f"inkypi-update-{int(time.time())}"

        if _mod._systemd_available():
            _mod._set_update_state(True, f"{unit}.service")
            try:
                _mod._start_update_via_systemd(
                    unit,
                    script_path or "/usr/local/inkypi/install/do_update.sh",
                    target_tag=target_tag,
                )
            except Exception:
                # If systemd-run fails unexpectedly, fall back to thread runner
                _mod.logger.exception(
                    "systemd-run failed; falling back to thread runner"
                )
                _mod._start_update_fallback_thread(script_path)
        else:
            _mod._set_update_state(True, None)
            _mod._start_update_fallback_thread(script_path)

        return jsonify(
            {
                "success": True,
                "running": True,
                "unit": _mod._UPDATE_STATE.get("unit"),
                "message": "Update started. Watch the Logs panel for progress.",
            }
        )
    except Exception as e:
        _mod.logger.exception("/settings/update error")
        return json_internal_error("start update", details={"error": str(e)})


@_mod.settings_bp.route("/settings/update_status")
def update_status():
    try:
        import subprocess

        running = bool(_mod._UPDATE_STATE.get("running"))
        unit = _mod._UPDATE_STATE.get("unit")
        started_at = _mod._UPDATE_STATE.get("started_at")

        # Auto-clear stale update state
        if running:
            cleared = False
            # Check if the systemd transient unit has finished
            if unit and _mod._systemd_available():
                try:
                    result = subprocess.run(
                        ["systemctl", "is-active", unit],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    status = result.stdout.strip()
                    if status not in ("active", "activating"):
                        _mod._UPDATE_STATE["last_unit"] = unit
                        _mod._set_update_state(False, None)
                        cleared = True
                except Exception:
                    pass
            # Timeout fallback: force-clear if started >30 min ago
            if (
                not cleared
                and started_at
                and (time.time() - float(started_at)) > _mod._UPDATE_TIMEOUT_SECONDS
            ):
                _mod._UPDATE_STATE["last_unit"] = unit
                _mod._set_update_state(False, None)

            # Re-read after potential clear
            running = bool(_mod._UPDATE_STATE.get("running"))
            unit = _mod._UPDATE_STATE.get("unit")
            started_at = _mod._UPDATE_STATE.get("started_at")

        return jsonify(
            {
                "running": running,
                "unit": unit,
                "started_at": started_at,
            }
        )
    except Exception as e:
        return json_internal_error("update status", details={"error": str(e)})


@_mod.settings_bp.route("/api/version")
def api_version():
    """Return current and latest version info."""
    try:
        current = current_app.config.get("APP_VERSION", "unknown")
        latest = _mod._check_latest_version()
        update_available = False
        if latest and current != "unknown":
            update_available = _mod._semver_gt(latest, current)
        return jsonify(
            {
                "current": current,
                "latest": latest,
                "update_available": update_available,
                "update_running": bool(_mod._UPDATE_STATE.get("running")),
                "release_notes": _mod._VERSION_CACHE.get("release_notes"),
            }
        )
    except Exception as e:
        return json_internal_error("version check", details={"error": str(e)})
