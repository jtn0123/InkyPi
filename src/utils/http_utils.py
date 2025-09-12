from __future__ import annotations

import logging
import threading
from typing import Any

import requests
from flask import Request, jsonify, request, g
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


def _get_or_set_request_id() -> str | None:
    """Return a stable per-request id if a request context exists.

    - Prefer an existing value in flask.g
    - Else prefer inbound header 'X-Request-Id'
    - Else generate a new uuid4 and store in flask.g
    - If no request context, return None
    """
    try:
        # Ensure we have a request context
        _ = request  # may raise if outside request context
    except Exception:
        return None
    try:
        rid_existing: str | None = getattr(g, "request_id", None)
        if rid_existing is not None and rid_existing != "":
            return rid_existing
        # Prefer inbound X-Request-Id if provided by client/proxy
        rid_hdr: str | None = request.headers.get("X-Request-Id")
        if rid_hdr is not None and rid_hdr != "":
            g.request_id = rid_hdr
            return rid_hdr
        # Generate
        import uuid

        rid_gen: str = str(uuid.uuid4())
        g.request_id = rid_gen
        return rid_gen
    except Exception:
        return None


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
    rid = _get_or_set_request_id()
    if rid is not None:
        payload["request_id"] = rid
    return jsonify(payload), status


def json_success(message: str | None = None, status: int = 200, **payload: Any):
    body: dict[str, Any] = {"success": True}
    if message is not None:
        body["message"] = message
    body.update(payload)
    rid = _get_or_set_request_id()
    if rid is not None:
        body["request_id"] = rid
    return jsonify(body), status


def json_internal_error(
    context: str,
    *,
    status: int = 500,
    code: int | str | None = "internal_error",
    details: dict[str, Any] | None = None,
):
    """Return a standardized internal error JSON while preserving existing error strings.

    - Keeps top-level error as a generic string for backward compatibility/tests
    - Adds structured details including a required context and optional hint
    """
    ctx: dict[str, Any] = {"context": context}
    if details:
        try:
            ctx.update(details)
        except Exception:
            pass
    return json_error("An internal error occurred", status=status, code=code, details=ctx)


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

# Use a thread-local container to avoid sharing sessions across threads.
_thread_local = threading.local()

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


def _build_session() -> requests.Session:
    s = requests.Session()
    adapter = HTTPAdapter(max_retries=_build_retry())
    s.headers.update(DEFAULT_HEADERS)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s


def get_shared_session() -> requests.Session:
    """Return a requests.Session unique to the current thread."""
    session: requests.Session | None = getattr(_thread_local, "session", None)
    if session is None:
        session = _build_session()
        _thread_local.session = session
    return session


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
    if hasattr(_thread_local, "session"):
        delattr(_thread_local, "session")
