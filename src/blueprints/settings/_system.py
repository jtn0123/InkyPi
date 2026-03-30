"""System control route handlers (shutdown, client logging)."""

import subprocess
import time

from flask import jsonify, request

import blueprints.settings as _mod
from utils.http_utils import json_error, json_internal_error


@_mod.settings_bp.route("/settings/client_log", methods=["POST"])
def client_log():
    """Accept lightweight client logs and emit them to server logs.

    Intended for front-end flows (e.g., browser geolocation) where we need
    visibility in terminal logs without failing the UX if logging fails.
    """
    try:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return json_error("Request body must be a JSON object", status=400)
        level = str(data.get("level") or "info").lower()
        message = str(data.get("message") or "")
        extra = data.get("extra")
        # Render extra as compact string to avoid noisy logs
        try:
            import json as _json

            extra_str = (
                _json.dumps(extra, separators=(",", ":")) if extra is not None else "{}"
            )
        except Exception:
            extra_str = str(extra)

        line = f"client_log | level={level} msg={message} extra={extra_str}"
        if level == "debug":
            _mod.logger.debug(line)
        elif level in ("warn", "warning"):
            _mod.logger.warning(line)
        elif level in ("err", "error"):
            _mod.logger.error(line)
        else:
            _mod.logger.info(line)
        return jsonify({"success": True})
    except Exception:
        _mod.logger.exception("/settings/client_log failure")
        return json_internal_error(
            "client_log", details={"hint": "Check payload shape."}
        )


@_mod.settings_bp.route("/shutdown", methods=["POST"])
def shutdown():
    """Reboot or shut down the device.

    Rate-limited to one call per 30 seconds to prevent accidental repeats.
    """
    now = time.monotonic()
    with _mod._shutdown_lock:
        if now - _mod._last_shutdown_time < _mod._SHUTDOWN_COOLDOWN_SECONDS:
            remaining = int(
                _mod._SHUTDOWN_COOLDOWN_SECONDS - (now - _mod._last_shutdown_time)
            )
            return json_error(
                f"Please wait {remaining}s before requesting another reboot/shutdown",
                status=429,
            )
        _mod._last_shutdown_time = now

    data = request.get_json(silent=True)
    if (
        data is None
        and request.content_type
        and "application/json" in request.content_type
    ):
        return json_error("Invalid JSON payload", status=400)
    if not isinstance(data, dict):
        data = {}
    try:
        if data.get("reboot"):
            _mod.logger.info("Reboot requested")
            subprocess.run(["sudo", "reboot"], check=True)
        else:
            _mod.logger.info("Shutdown requested")
            subprocess.run(["sudo", "shutdown", "-h", "now"], check=True)
        return jsonify({"success": True})
    except subprocess.CalledProcessError as e:
        _mod.logger.exception("Failed to execute shutdown command")
        return json_internal_error("shutdown", details={"error": str(e)})
