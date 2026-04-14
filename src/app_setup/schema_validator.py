"""Dev-only JSON response schema validator middleware (JTN-664).

Registers a single ``@app.after_request`` hook that validates JSON responses
for a curated set of endpoints against their canonical ``TypedDict`` in
``schemas.responses``. Drift is logged at WARNING level and the response is
returned unchanged — this middleware is strictly advisory.

Gate: the caller wires this in ``create_app()`` behind ``DEV_MODE`` or the
``INKYPI_STRICT_SCHEMAS=1`` escape hatch. It is never active in production.
"""

from __future__ import annotations

import logging

from flask import Flask, request

from schemas.endpoint_map import ENDPOINT_SCHEMAS
from schemas.validator import validate_typeddict

logger = logging.getLogger(__name__)


def register(app: Flask) -> None:
    """Attach the dev-only response schema validator to *app*."""

    @app.after_request
    def _validate_response_schema(response):
        try:
            if response.mimetype != "application/json":
                return response
            endpoint = request.endpoint
            if endpoint is None or endpoint not in ENDPOINT_SCHEMAS:
                return response

            payload = response.get_json(silent=True)
            if payload is None:
                return response

            errors = validate_typeddict(payload, ENDPOINT_SCHEMAS[endpoint])
            for err in errors:
                logger.warning("schema drift: %s at %s", endpoint, err)
        except Exception:
            # Advisory only — never allow the validator to break a response.
            logger.debug("schema validator hook failed", exc_info=True)
        return response
