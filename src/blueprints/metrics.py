"""Prometheus /metrics endpoint (JTN-334).

NOTE: This endpoint is intentionally accessible WITHOUT authentication.
Prometheus scrapers need to reach /metrics on a regular polling interval and
cannot easily carry session cookies or CSRF tokens.  Exposing counters and
gauges is considered safe because the data is read-only and contains no
user-identifying information.
"""

from __future__ import annotations

from flask import Blueprint, Response

try:
    from prometheus_client.exposition import generate_latest
except ModuleNotFoundError:
    generate_latest = None

from utils.metrics import metrics_registry, update_uptime

metrics_bp = Blueprint("metrics", __name__)

_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


@metrics_bp.route("/metrics", methods=["GET"])
def prometheus_metrics():
    """Return all InkyPi metrics in Prometheus text exposition format."""
    if generate_latest is None:
        return Response(
            b"# prometheus_client not installed; metrics disabled\n",
            status=200,
            content_type=_CONTENT_TYPE,
        )
    update_uptime()
    data = generate_latest(metrics_registry)
    return Response(data, status=200, content_type=_CONTENT_TYPE)
