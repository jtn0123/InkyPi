"""Blueprint: POST /api/client-log — receive and log browser console messages (JTN-481).

Accepts JSON reports from the console.warn/error shim in client_log_reporter.js,
validates the schema, caps field sizes, and logs as WARNING so the server-side
SecretRedactionFilter (JTN-364) strips any secrets before they reach disk.

Only active when the page opts in via:
    <meta name="client-log-enabled" content="1">

Rate-limited per remote IP using TokenBucket (capacity=10, refill=1/s).
"""

from __future__ import annotations

import json
import logging

from flask import Blueprint, Response, request

from utils.http_utils import json_error
from utils.rate_limit import TokenBucket

logger = logging.getLogger(__name__)

client_log_bp = Blueprint("client_log", __name__)

# ---------------------------------------------------------------------------
# Rate limiting — 10-token burst, refills at 1 token/s
# ---------------------------------------------------------------------------
_rate_limiter: TokenBucket = TokenBucket(capacity=10, refill_rate=1.0)

# ---------------------------------------------------------------------------
# Size limits
# ---------------------------------------------------------------------------
_MESSAGE_MAX = 2048   # bytes for message field
_ARGS_MAX = 4096      # bytes for args field
_BODY_MAX = 16_384    # 16 KB total body

# Accepted levels — info/debug rejected to avoid noise
_ACCEPTED_LEVELS = frozenset({"warn", "error"})


def _cap(value: object, max_len: int) -> str:
    """Coerce *value* to str and cap at *max_len* characters."""
    return str(value)[:max_len]


def _strip_newlines(value: str) -> str:
    """Replace CR/LF with spaces to prevent log-injection (Sonar S5145)."""
    return value.replace("\r", " ").replace("\n", " ")


@client_log_bp.route("/api/client-log", methods=["POST"])
def receive_client_log() -> tuple[Response, int] | Response:
    """Accept a browser console.warn/error report and emit it as a WARNING log entry.

    Returns 204 on success so the browser-side script has a cheap ack with
    no body to parse.
    """
    # --- body size guard --------------------------------------------------
    content_length = request.content_length
    if content_length is not None and content_length > _BODY_MAX:
        return json_error("Request body too large", status=413)

    raw_body = request.get_data(as_text=False)
    if len(raw_body) > _BODY_MAX:
        return json_error("Request body too large", status=413)

    # --- rate limiting ----------------------------------------------------
    remote_ip = request.remote_addr or "unknown"
    if not _rate_limiter.try_acquire(remote_ip):
        return json_error("Rate limit exceeded", status=429)

    # --- parse & validate -------------------------------------------------
    try:
        data = json.loads(raw_body)
    except ValueError:
        return json_error("Request body must be valid JSON", status=400)

    if not isinstance(data, dict):
        return json_error("Request body must be a JSON object", status=400)

    level = data.get("level", "")
    if level not in _ACCEPTED_LEVELS:
        return json_error(
            f"Invalid level '{level}': must be one of {sorted(_ACCEPTED_LEVELS)}",
            status=400,
        )

    # --- build sanitised report -------------------------------------------
    # Strip CR/LF from each field to prevent log injection (Sonar S5145).
    # SecretRedactionFilter (JTN-364) handles secret stripping downstream.
    report: dict[str, object] = {
        "level": level,
    }
    if "message" in data:
        report["message"] = _strip_newlines(_cap(data["message"], _MESSAGE_MAX))
    if "args" in data:
        report["args"] = _strip_newlines(_cap(data["args"], _ARGS_MAX))
    if "url" in data:
        report["url"] = _strip_newlines(_cap(data["url"], _MESSAGE_MAX))
    if "ts" in data:
        report["ts"] = _strip_newlines(_cap(data["ts"], 64))

    logger.warning("client log [%s]: %s", level, json.dumps(report))

    return Response(status=204)


@client_log_bp.route("/api/client-log", methods=["GET"])
def receive_client_log_get() -> tuple[Response, int]:
    """Explicitly reject GET to provide a clear error instead of 405 from Flask."""
    return json_error("Method not allowed", status=405)
