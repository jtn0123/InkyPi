"""System control route handler (reboot and shutdown)."""

import subprocess

from flask import Response, request

from blueprints.settings import logger, settings_bp
from utils.api_responses import (
    JsonResponse,
    json_error,
    json_internal_error,
    json_success,
)
from utils.rate_limit import CooldownLimiter

# Shutdown rate limiting
_shutdown_limiter = CooldownLimiter(30)


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
