from __future__ import annotations

import logging
from typing import Any

import requests
from flask import Request, jsonify, request
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


class APIError(Exception):
    """Typed API error that can be raised within routes to return JSON errors.

    Attributes
    ----------
    message: str
        Human-readable error message
    status: int
        HTTP status code (default 400)
    code: Optional[int | str]
        Optional application-specific error code
    details: Optional[dict[str, Any]]
        Optional structured details to aid clients
    """

    def __init__(
        self,
        message: str,
        status: int = 400,
        code: int | str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.details = details


def json_error(
    message: str,
    status: int = 400,
    code: int | str | None = None,
    details: dict[str, Any] | None = None,
):
    payload: dict[str, Any] = {"error": message}
    if code is not None:
        payload["code"] = code
    if details is not None:
        payload["details"] = details
    return jsonify(payload), status


def json_success(message: str | None = None, status: int = 200, **payload: Any):
    body: dict[str, Any] = {"success": True}
    if message is not None:
        body["message"] = message
    body.update(payload)
    return jsonify(body), status


def wants_json(req: Request | None = None) -> bool:
    """Heuristic to decide if the current request expects JSON.

    We keep this conservative to avoid affecting HTML routes.
    """
    try:
        r = req or request
        accept_json = (
            r.accept_mimetypes.accept_json and not r.accept_mimetypes.accept_html
        )
        is_api_path = r.path.startswith("/api/")
        has_json = False
        try:
            has_json = bool(r.is_json or r.get_json(silent=True) is not None)
        except Exception:
            has_json = False
        return bool(accept_json or is_api_path or has_json)
    except Exception:
        return False


# ---- HTTP client helpers ----------------------------------------------------

_session: requests.Session | None = None

# Conservative defaults that keep tests fast (no backoff sleeps) while providing resiliency
DEFAULT_TIMEOUT_SECONDS: float = 20.0
DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": "InkyPi/1.0 (+https://github.com/fatihak/InkyPi)"
}


def _build_retry() -> Retry:
    # Retry idempotent methods on common transient failures
    return Retry(
        total=3,
        connect=3,
        read=3,
        status=3,
        backoff_factor=0.0,  # keep tests snappy; no sleep between retries
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=(
            "HEAD",
            "GET",
            "PUT",
            "DELETE",
            "OPTIONS",
            "TRACE",
        ),
        raise_on_status=False,
    )


def get_shared_session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        adapter = HTTPAdapter(max_retries=_build_retry())
        s.headers.update(DEFAULT_HEADERS)
        s.mount("http://", adapter)
        s.mount("https://", adapter)
        _session = s
    return _session


def http_get(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float | tuple[float, float] | None = None,
    stream: bool = False,
    allow_redirects: bool = True,
) -> requests.Response:
    """Perform a GET using a shared session with retries and sane defaults.

    - Adds a default User-Agent header
    - Applies a default timeout if none is provided
    - Uses a shared requests.Session configured with HTTPAdapter retries
    - SSL verification is enabled by default (do not disable)
    """
    session = get_shared_session()
    final_headers = dict(DEFAULT_HEADERS)
    if headers:
        final_headers.update(headers)
    return session.get(
        url,
        params=params,
        headers=final_headers,
        timeout=DEFAULT_TIMEOUT_SECONDS if timeout is None else timeout,
        stream=stream,
        allow_redirects=allow_redirects,
    )


def _reset_shared_session_for_tests() -> None:
    """Reset the shared session (testing only)."""
    global _session
    _session = None
