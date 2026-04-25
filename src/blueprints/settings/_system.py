"""System control route handlers (shutdown, client logging)."""

import subprocess

from flask import Response, request

import blueprints.settings as _mod
from utils.http_utils import json_error, json_internal_error, json_success


def _sanitize_log_value(value: str, max_len: int = 500) -> str:
    """Strip control characters from client input to prevent log injection."""
    return value.replace("\n", "").replace("\r", "").replace("\x00", "")[:max_len]


@_mod.settings_bp.route("/settings/client_log", methods=["POST"])  # type: ignore
def client_log() -> tuple[object, int] | Response:
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

        level = _sanitize_log_value(level, max_len=20)
        message = _sanitize_log_value(message)
        extra_str = _sanitize_log_value(extra_str)
        line = f"client_log | level={level} msg={message} extra={extra_str}"
        if level == "debug":
            _mod.logger.debug(line)
        elif level in ("warn", "warning"):
            _mod.logger.warning(line)
        elif level in ("err", "error"):
            _mod.logger.error(line)
        else:
            _mod.logger.info(line)
        return json_success()
    except Exception:
        _mod.logger.exception("/settings/client_log failure")
        return json_internal_error(
            "client_log", details={"hint": "Check payload shape."}
        )


@_mod.settings_bp.route("/shutdown", methods=["POST"])  # type: ignore
def shutdown() -> tuple[object, int] | Response:
    """Reboot or shut down the device.

    Rate-limited to one call per 30 seconds to prevent accidental repeats.
    """
    allowed, retry_after = _mod._shutdown_limiter.check()
    if not allowed:
        remaining = int(retry_after)
        return json_error(
            f"Please wait {remaining}s before requesting another reboot/shutdown",
            status=429,
        )
    # Reserve the slot to prevent concurrent requests
    _mod._shutdown_limiter.record()

    data = request.get_json(silent=True)
    if (
        data is None
        and request.content_type
        and "application/json" in request.content_type
    ):
        # Roll back reservation on input validation failure
        _mod._shutdown_limiter.reset()
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
        # Refresh the cooldown timestamp to the actual success time
        _mod._shutdown_limiter.record()
        return json_success()
    except subprocess.CalledProcessError as e:
        # Roll back so the cooldown isn't consumed by a failed attempt
        _mod._shutdown_limiter.reset()
        _mod.logger.exception("Failed to execute shutdown command")
        return json_internal_error("shutdown", details={"error": str(e)})
