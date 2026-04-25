"""Flask error handlers extracted from inkypi.py (JTN-289)."""

from __future__ import annotations

import logging

from flask import Flask, Response, make_response, render_template
from werkzeug.exceptions import HTTPException

from utils.http_utils import APIError, json_error, json_internal_error, wants_json

logger = logging.getLogger(__name__)


def register_error_handlers(app: Flask) -> None:
    """Register JSON-aware error handlers for common HTTP status codes."""

    @app.errorhandler(APIError)  # type: ignore
    def _handle_api_error(err: APIError) -> tuple[dict[str, object], int] | Response:
        return json_error(
            err.message, status=err.status, code=err.code, details=err.details
        )

    @app.errorhandler(400)  # type: ignore
    def _handle_bad_request(err: object) -> tuple[dict[str, object], int] | Response:
        if wants_json():
            return json_error("Bad request", status=400)
        return make_response("Bad request", 400)

    @app.errorhandler(404)  # type: ignore
    def _handle_not_found(
        err: object,
    ) -> tuple[dict[str, object], int] | Response | tuple[str, int]:
        if wants_json():
            return json_error("Not found", status=404)
        return render_template("404.html"), 404

    @app.errorhandler(415)  # type: ignore
    def _handle_unsupported_media_type(
        err: object,
    ) -> tuple[dict[str, object], int] | Response:
        if wants_json():
            return json_error("Unsupported media type", status=415)
        return make_response("Unsupported media type", 415)

    @app.errorhandler(Exception)  # type: ignore
    def _handle_unexpected_error(
        err: Exception,
    ) -> Response | tuple[dict[str, object], int]:
        if isinstance(err, HTTPException):
            return err.get_response()
        try:
            logger.exception("Unhandled exception: %s", err)
        except Exception:
            pass
        if wants_json():
            return json_internal_error(
                "unhandled application error",
                details={
                    "hint": "Check server logs for stack trace; enable DEV mode for more diagnostics.",
                },
            )
        return make_response("Internal Server Error", 500)
