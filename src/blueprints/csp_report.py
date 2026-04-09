"""CSP violation report endpoint.

Receives Content-Security-Policy violation reports from browsers and logs
them as WARNING-level messages with redacted source URLs.

This endpoint intentionally requires NO authentication — browsers cannot
pass auth headers with CSP reports.
"""

from __future__ import annotations

import json
import logging
import re

from flask import Blueprint, Response, request

from utils.rate_limiter import SlidingWindowLimiter

logger = logging.getLogger(__name__)

csp_report_bp = Blueprint("csp_report", __name__)

# Allow up to 20 CSP reports per IP per minute — more than enough for
# legitimate browser reports; blocks flooded or replayed traffic.
_csp_report_limiter = SlidingWindowLimiter(20, 60)

_SOURCE_FILE_RE = re.compile(r'"source-file"\s*:\s*"([^"]*)"')
_DOCUMENT_URI_RE = re.compile(r'"document-uri"\s*:\s*"([^"]*)"')

# CSP report content-types (legacy and modern Reporting API)
_ACCEPTED_CONTENT_TYPES = {
    "application/csp-report",
    "application/json",
    "application/reports+json",
}


def _redact_url(url: str) -> str:
    """Strip query string and fragment from a URL for safe logging."""
    # Keep scheme + host + path; drop ?query and #fragment
    for sep in ("?", "#"):
        url = url.split(sep)[0]
    return url


def _parse_report(body: bytes) -> dict:
    """Parse a CSP report body; return an empty dict on failure."""
    if not body:
        return {}
    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return {}

    # Legacy format: {"csp-report": {...}}
    if isinstance(data, dict) and "csp-report" in data:
        return data["csp-report"]

    # Modern Reporting API: [{"type": "csp-violation", "body": {...}}, ...]
    if isinstance(data, list):
        for entry in data:
            if isinstance(entry, dict) and entry.get("type") in (
                "csp-violation",
                "csp_violation",
            ):
                return entry.get("body", {})
        # Fall back to first entry body if no typed entry found
        if data and isinstance(data[0], dict):
            return data[0].get("body", data[0])

    if isinstance(data, dict):
        return data

    return {}


def _sanitise_report(report: dict) -> dict:
    """Return a copy of the report with URLs redacted."""
    sanitised = {}
    url_keys = {"document-uri", "referrer", "source-file", "blocked-uri"}
    for key, value in report.items():
        if key in url_keys and isinstance(value, str):
            sanitised[key] = _redact_url(value)
        else:
            sanitised[key] = value
    return sanitised


@csp_report_bp.route("/api/csp-report", methods=["POST"])
def receive_csp_report() -> Response:
    """Accept a CSP violation report and log it.

    Returns 204 No Content unconditionally (do not reveal processing details
    to potential attackers flooding this endpoint).
    """
    addr = request.remote_addr or "unknown"
    allowed, _ = _csp_report_limiter.check(addr)
    if not allowed:
        # Still return 204 — don't fingerprint the rate limiter to browsers
        return Response(status=204)

    content_type = (request.content_type or "").split(";")[0].strip().lower()
    if content_type and content_type not in _ACCEPTED_CONTENT_TYPES:
        logger.debug(
            "CSP report endpoint received unexpected content-type: %s", content_type
        )

    body = request.get_data(cache=False)
    report = _parse_report(body)
    sanitised = _sanitise_report(report)
    logger.warning("CSP violation: %s", json.dumps(sanitised))

    return Response(status=204)
