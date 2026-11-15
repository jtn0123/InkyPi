"""System control route handlers (shutdown, client logging)."""

import subprocess

from flask import Response, request

from blueprints.settings import logger, settings_bp
from utils.http_utils import JsonResponse, json_error, json_internal_error, json_success
from utils.rate_limit import CooldownLimiter

# Shutdown rate limiting
_shutdown_limiter = CooldownLimiter(30)


def _sanitize_log_value(value: str, max_len: int = 500) -> str:
    """Strip control characters from client input to prevent log injection."""
    return value.replace("\n", "").replace("\r", "").replace("\x00", "")[:max_len]


@settings_bp.route("/settings/client_log", methods=["POST"])
def client_log() -> JsonResponse | Response:
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
            logger.debug(line)
        elif level in ("warn", "warning"):
            logger.warning(line)
        elif level in ("err", "error"):
            logger.error(line)
        else:
            logger.info(line)
        return json_success()
    except Exception:
        logger.exception("/settings/client_log failure")
        return json_internal_error(
            "client_log", details={"hint": "Check payload shape."}
        )


@settings_bp.route("/shutdown", methods=["POST"])
def shutdown() -> JsonResponse | Response:
    """Reboot or shut down the device.

    Rate-limited to one call per 30 seconds to prevent accidental repeats.
    """
    # Test and reserve the slot in one step, so two requests can't both pass.
    allowed, retry_after = _shutdown_limiter.acquire()
    if not allowed:
        remaining = int(retry_after)
        return json_error(
            f"Please wait {remaining}s before requesting another reboot/shutdown",
            status=429,
        )

    data = request.get_json(silent=True)
    if (
        data is None
        and request.content_type
        and "application/json" in request.content_type
    ):
        # Roll back reservation on input validation failure
        _shutdown_limiter.reset()
        return json_error("Invalid JSON payload", status=400)
    if not isinstance(data, dict):
        data = {}
    try:
        if data.get("reboot"):
            logger.info("Reboot requested")
            subprocess.run(["sudo", "reboot"], check=True)
        else:
            logger.info("Shutdown requested")
            subprocess.run(["sudo", "shutdown", "-h", "now"], check=True)
        # Refresh the cooldown timestamp to the actual success time
        _shutdown_limiter.record()
        return json_success()
    except subprocess.CalledProcessError:
        # Roll back so the cooldown isn't consumed by a failed attempt
        _shutdown_limiter.reset()
        logger.exception("Failed to execute shutdown command")
        return json_internal_error("shutdown")
