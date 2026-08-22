"""Prometheus /metrics endpoint (JTN-334).

NOTE: This endpoint is intentionally accessible WITHOUT authentication.
Prometheus scrapers need to reach /metrics on a regular polling interval and
cannot easily carry session cookies or CSRF tokens.  Exposing counters and
gauges is considered safe because the data is read-only and contains no
user-identifying information.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from flask import Blueprint, Response

from utils.metrics import metrics_registry, update_uptime

# prometheus_client is a declared dependency, but the import stays guarded so a
# partial install on the device degrades to a disabled /metrics endpoint rather
# than a 500. Bound via a private alias and declared once, because importing
# directly into the annotated name is a redefinition, and annotating only one
# branch makes mypy treat that branch's type as definitive.
generate_latest: Callable[..., bytes] | None
try:
    from prometheus_client.exposition import generate_latest as _imported
except ModuleNotFoundError:  # pragma: no cover - exercised only without the dep
    generate_latest = None
else:
    generate_latest = _imported

metrics_bp = Blueprint("metrics", __name__)

_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


@metrics_bp.route("/metrics", methods=["GET"])
def prometheus_metrics() -> Response:
    """Return all InkyPi metrics in Prometheus text exposition format."""
    if generate_latest is None:
        return Response(
            b"# prometheus_client not installed; metrics disabled\n",
            status=200,
            content_type=_CONTENT_TYPE,
        )
    update_uptime()
    data = generate_latest(cast(Any, metrics_registry))
    return Response(data, status=200, content_type=_CONTENT_TYPE)
