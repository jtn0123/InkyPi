"""Blueprint: POST /api/client-error — receive and log browser JS error reports (JTN-454).

Accepts JSON error reports from window.onerror / unhandledrejection handlers,
validates the schema, caps field sizes, and logs as WARNING so the server-side
SecretRedactionFilter (JTN-364) strips any secrets before they reach disk.

Rate-limited per remote IP using TokenBucket (capacity=5, refill=0.5/s ≈ 30/min).
"""

from __future__ import annotations

import json
import logging

from flask import Blueprint, Response, request

from utils.http_utils import json_error
from utils.rate_limit import TokenBucket

logger = logging.getLogger(__name__)

client_error_bp = Blueprint("client_error", __name__)

# ---------------------------------------------------------------------------
# Rate limiting — 5-token burst, refills at 0.5 tokens/s (30 req/min sustained)
# ---------------------------------------------------------------------------
_rate_limiter: TokenBucket = TokenBucket(capacity=5, refill_rate=0.5)

# ---------------------------------------------------------------------------
# Size limits
# ---------------------------------------------------------------------------
_FIELD_MAX = 2048  # bytes per field
_BODY_MAX = 16_384  # 16 KB total body

# Required fields that must be present in the JSON payload.
_REQUIRED_FIELDS = frozenset({"message"})

# All accepted fields (others are silently dropped).
_ACCEPTED_FIELDS = frozenset(
    {"message", "source", "line", "column", "stack", "user_agent", "url"}
)


def _cap(value: object, max_len: int = _FIELD_MAX) -> str:
    """Coerce *value* to str and cap at *max_len* characters."""
    return str(value)[:max_len]


def _strip_newlines(value: str) -> str:
    """Replace CR/LF with spaces to prevent log-injection (Sonar S5145)."""
    return value.replace("\r", " ").replace("\n", " ")


@client_error_bp.route("/api/client-error", methods=["POST"])
def receive_client_error() -> tuple[Response, int] | Response:
    """Accept a browser JS error report and emit it as a WARNING log entry.

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

    missing = _REQUIRED_FIELDS - data.keys()
    if missing:
        return json_error(
            f"Missing required field(s): {', '.join(sorted(missing))}", status=400
        )

    # --- build sanitised report -------------------------------------------
    # Strip CR/LF from each field to prevent log injection (Sonar S5145).
    # SecretRedactionFilter (JTN-364) handles secret stripping downstream.
    report: dict[str, object] = {}
    for field in _ACCEPTED_FIELDS:
        if field in data:
            report[field] = _strip_newlines(_cap(data[field]))

    logger.warning("client error: %s", json.dumps(report))

    return Response(status=204)


@client_error_bp.route("/api/client-error", methods=["GET"])
def receive_client_error_get() -> tuple[Response, int]:
    """Explicitly reject GET to provide a clear error instead of 405 from Flask."""
    return json_error("Method not allowed", status=405)
