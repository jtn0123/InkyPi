"""Blueprint: GET /errors + POST /errors/clear — browser-side error log viewer (JTN-586).

Surfaces captured client-side error reports (console.warn / console.error
forwarded by client_log_reporter.js, collected by /api/client-log when the
INKYPI_TEST_CAPTURE_CLIENT_LOG env var is set in dev mode) and provides a
"Clear All" action backed by an in-app confirmation modal — never window.confirm.
"""

from __future__ import annotations

import logging

from flask import Blueprint, render_template

from blueprints.client_log import get_captured_reports, reset_captured_reports
from utils.http_utils import json_success

logger = logging.getLogger(__name__)

errors_bp = Blueprint("errors", __name__)


@errors_bp.route("/errors", methods=["GET"])
def errors_page() -> str:
    """Render the /errors page showing captured client-side error reports."""
    reports = get_captured_reports()
    return render_template("errors.html", reports=reports)


@errors_bp.route("/errors/clear", methods=["POST"])
def errors_clear():
    """Clear all captured client-side error reports.

    Called by the in-app confirmation modal on /errors — NOT via window.confirm.
    Returns JSON so the JS handler can check for success/failure.
    """
    reset_captured_reports()
    logger.info("Client error log cleared via /errors/clear")
    return json_success("Error logs cleared")
