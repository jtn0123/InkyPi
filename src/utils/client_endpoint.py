"""Shared helpers for browser-side reporting endpoints (JTN-454, JTN-481).

The /api/client-error and /api/client-log endpoints share the same
size + rate-limit + JSON parse boilerplate. This module exposes a
single helper that performs all three checks and returns either the
parsed dict or an error response that the caller can return directly.
"""

from __future__ import annotations

import json
from typing import Any

from flask import Response, request

from utils.http_utils import json_error
from utils.rate_limit import TokenBucket


def parse_client_report(
    rate_limiter: TokenBucket, body_max: int
) -> tuple[dict[str, Any] | None, Response | tuple[Response, int] | None]:
    """Validate body size, rate-limit, and parse JSON.

    Returns ``(data, None)`` on success or ``(None, error_response)`` on
    failure. Callers should ``return`` the error response immediately when it
    is non-None.
    """
    content_length = request.content_length
    if content_length is not None and content_length > body_max:
        return None, json_error("Request body too large", status=413)

    raw_body = request.get_data(as_text=False)
    if len(raw_body) > body_max:
        return None, json_error("Request body too large", status=413)

    remote_ip = request.remote_addr or "unknown"
    if not rate_limiter.try_acquire(remote_ip):
        return None, json_error("Rate limit exceeded", status=429)

    try:
        data = json.loads(raw_body)
    except ValueError:
        return None, json_error("Request body must be valid JSON", status=400)

    if not isinstance(data, dict):
        return None, json_error("Request body must be a JSON object", status=400)

    return data, None


def strip_newlines(value: str) -> str:
    """Replace CR/LF with spaces to prevent log-injection (Sonar S5145)."""
    return value.replace("\r", " ").replace("\n", " ")
