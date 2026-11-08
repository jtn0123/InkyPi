"""HTTP helpers and canonical JSON response envelope (JTN-500).

Canonical JSON envelope
-----------------------
All JSON API routes should return responses built via :func:`json_success` or
:func:`json_error` so clients can rely on a single stable shape.

Success envelope::

    {
        "success": true,
        "message": "<optional human-readable summary>",
        "request_id": "<uuid, when inside a request context>",
        ...payload fields (e.g. "data", "items", "metrics")...
    }

Error envelope::

    {
        "success": false,
        "error": "<human-readable message>",
        "code": "<optional app error code>",
        "details": { ... optional structured detail ... },
        "request_id": "<uuid, when inside a request context>"
    }

Rules of thumb
~~~~~~~~~~~~~~
* Prefer ``json_success(message=..., data=..., meta=...)`` over
  ``jsonify({"success": True, ...})`` so ``request_id`` and future envelope
  fields are added automatically.
* For errors, raise :class:`APIError` or return ``json_error(...)``.  Do not
  return ``jsonify({"success": False, "error": "..."})`` directly — that shape
  skips ``request_id`` and bypasses the central error logging path.
* Pagination envelopes should place page data under ``items`` and cursor
  information under ``next_cursor``/``meta``.
* Pure data read endpoints (e.g. ``/api/version/info``) MAY return a raw JSON
  object without the ``success`` key for backwards compatibility, but any new
  endpoint should use the canonical envelope.
"""

from __future__ import annotations

import re
from html import escape
from typing import Any
from urllib.parse import quote

from flask import Request, g, jsonify, request
from flask.wrappers import Response as FlaskResponse

from utils.form_utils import sanitize_response_value

#: What :func:`json_error` and :func:`json_success` actually return.
#:
#: Normally the first element is a ``Response`` from ``jsonify``, but both fall
#: back to a plain ``dict`` when there is no application context for jsonify to
#: use. Callers used to annotate only the ``Response`` half, so a dozen handlers
#: across the app were typed as something narrower than the value they return.
JsonResponse = tuple["FlaskResponse | dict[str, Any]", int]

#: Accepted shape for an inbound ``X-Request-Id``. Covers uuids, hex ids, and
#: the ``trace:span`` forms proxies emit, without admitting markup.
_REQUEST_ID_RE = re.compile(r"[A-Za-z0-9._:-]{1,128}")


def _sanitize_details(details: dict[str, Any]) -> dict[str, Any]:
    """Recursively HTML-escape all string leaf values in *details*.

    Non-string scalars (int, bool, float, None) pass through unchanged.
    Nested dicts are traversed recursively.  Lists are sanitized element-wise.
    This is defense-in-depth: any user-derived string reaching the JSON error
    envelope will have angle brackets and ampersands escaped before serialisation.
    """

    def _sanitize(value: Any) -> Any:
        if isinstance(value, str):
            return sanitize_response_value(value)
        if isinstance(value, dict):
            return {k: _sanitize(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_sanitize(item) for item in value]
        return value

    return {k: _sanitize(v) for k, v in details.items()}


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
    except RuntimeError:
        return None
    try:
        rid_existing: str | None = getattr(g, "request_id", None)
        if rid_existing is not None and rid_existing != "":
            return escape(rid_existing, quote=True)
        # Prefer inbound X-Request-Id if provided by client/proxy.
        #
        # The value is echoed back in every json_error/json_success body, so an
        # unvalidated header is client-controlled data reflected in a response
        # (CodeQL py/reflective-xss). A request id is an opaque correlation
        # token, so anything outside a conservative charset is not one — reject
        # it and generate our own rather than trying to clean it up. Also
        # bounded, so a multi-megabyte header cannot ride along on every reply.
        rid_hdr: str | None = request.headers.get("X-Request-Id")
        if rid_hdr and _REQUEST_ID_RE.fullmatch(rid_hdr):
            # Escaped on the way out for the same reason `_sanitize_details`
            # escapes the details dict: it is a user-derived string reaching the
            # JSON envelope, and that policy applied to every such value except
            # this one. After the charset check above the escape is a no-op, so
            # this is consistency and defence in depth rather than the guard.
            # Annotated because this module is in the mypy strict subset and
            # `follow_imports = skip` hides form_utils' `-> str` declaration.
            rid_safe: str = escape(rid_hdr, quote=True)
            g.request_id = rid_safe
            return rid_safe
        # Generate
        import uuid

        rid_gen: str = str(uuid.uuid4())
        g.request_id = rid_gen
        return rid_gen
    except RuntimeError:
        return None


def json_error(
    message: str,
    status: int = 400,
    code: int | str | None = None,
    details: dict[str, Any] | None = None,
) -> JsonResponse:
    payload: dict[str, Any] = {"success": False, "error": message}
    if code is not None:
        payload["code"] = code
    if details is not None:
        payload["details"] = _sanitize_details(details)
    rid = _get_or_set_request_id()
    if rid is not None:
        payload["request_id"] = rid
    try:
        return jsonify(payload), status
    except RuntimeError:
        # Allow utility-level calls outside Flask application/request contexts.
        return payload, status


def json_success(
    message: str | None = None, status: int = 200, **payload: Any
) -> JsonResponse:
    body: dict[str, Any] = {"success": True}
    if message is not None:
        body["message"] = message
    body.update(payload)
    rid = _get_or_set_request_id()
    if rid is not None:
        body["request_id"] = rid
    try:
        return jsonify(body), status
    except RuntimeError:
        return body, status


def reissue_json_error(
    error_response: tuple[FlaskResponse | dict[str, Any], int],
    fallback_message: str,
) -> tuple[FlaskResponse | dict[str, Any], int]:
    """Rebuild an error response using a server-controlled message.

    This preserves only the HTTP status and never reuses upstream payload
    fields. The returned message is always server-controlled.
    """
    _, status = error_response
    try:
        safe_status = int(status)
    except (TypeError, ValueError):
        safe_status = 400
    if safe_status < 400 or safe_status > 599:
        safe_status = 400
    return json_error(
        fallback_message,
        status=safe_status,
    )


def json_internal_error(
    context: str,
    *,
    status: int = 500,
    code: int | str | None = "internal_error",
    details: dict[str, Any] | None = None,
) -> tuple[FlaskResponse | dict[str, Any], int]:
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
    return json_error(
        "An internal error occurred", status=status, code=code, details=ctx
    )


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


def content_disposition(disposition: str, filename: str) -> str:
    """Build a ``Content-Disposition`` value that is safe for any filename.

    HTTP headers must be latin-1; WSGI servers (waitress) raise
    ``UnicodeEncodeError`` -> 500 when a header contains e.g. an en dash from a
    user-chosen plugin instance name. Emit an ASCII ``filename="..."`` fallback
    (non-ASCII, quotes, backslashes and control chars replaced with ``_``) and,
    when the name is not plain ASCII, an RFC 5987 ``filename*`` with the
    original UTF-8 name so browsers still show it correctly.
    """
    ascii_name = "".join(
        ch if 0x20 <= ord(ch) < 0x7F and ch not in '"\\' else "_" for ch in filename
    )
    value = f'{disposition}; filename="{ascii_name}"'
    if ascii_name != filename:
        value += f"; filename*=UTF-8''{quote(filename, safe='')}"
    return value
