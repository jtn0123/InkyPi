from __future__ import annotations

import logging
from typing import Any, Optional

from flask import jsonify, Request, request


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

    def __init__(self, message: str, status: int = 400, code: Optional[int | str] = None, details: Optional[dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.details = details


def json_error(message: str, status: int = 400, code: Optional[int | str] = None, details: Optional[dict[str, Any]] = None):
    payload: dict[str, Any] = {"error": message}
    if code is not None:
        payload["code"] = code
    if details is not None:
        payload["details"] = details
    return jsonify(payload), status


def json_success(message: Optional[str] = None, status: int = 200, **payload: Any):
    body: dict[str, Any] = {"success": True}
    if message is not None:
        body["message"] = message
    body.update(payload)
    return jsonify(body), status


def wants_json(req: Optional[Request] = None) -> bool:
    """Heuristic to decide if the current request expects JSON.

    We keep this conservative to avoid affecting HTML routes.
    """
    try:
        r = req or request
        accept_json = r.accept_mimetypes.accept_json and not r.accept_mimetypes.accept_html
        is_api_path = r.path.startswith("/api/")
        has_json = False
        try:
            has_json = bool(r.is_json or r.get_json(silent=True) is not None)
        except Exception:
            has_json = False
        return bool(accept_json or is_api_path or has_json)
    except Exception:
        return False


