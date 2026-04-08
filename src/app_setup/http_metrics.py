"""HTTP request timing middleware for Prometheus metrics (JTN-362).

Registers before_request / after_request hooks that measure per-endpoint
latency and record it via the helpers in utils.metrics.

Endpoints excluded from measurement:
  * /metrics  — scraping the metrics endpoint itself would create noise and
                 a circular dependency on the counters.
  * /static/* — static assets are high-volume, low-signal, and already
                 cached at the edge in production.
"""

from __future__ import annotations

from time import perf_counter

from flask import Flask, g, request

from utils.metrics import record_http_request

_SKIP_PREFIXES = ("/metrics", "/static/")


def _should_skip(path: str) -> bool:
    return any(path == prefix or path.startswith(prefix) for prefix in _SKIP_PREFIXES)


def setup_http_metrics(app: Flask) -> None:
    """Register before/after request hooks that record HTTP timing metrics."""

    @app.before_request
    def _http_metrics_start():
        if _should_skip(request.path):
            return
        g._http_metrics_t0 = perf_counter()

    @app.after_request
    def _http_metrics_finish(response):
        t0 = getattr(g, "_http_metrics_t0", None)
        if t0 is None:
            return response
        duration = perf_counter() - t0

        # Prefer the url_rule (e.g. /history/image/<filename>) to avoid
        # cardinality explosion from raw paths with dynamic segments.
        rule = request.url_rule
        endpoint = rule.rule if rule is not None else request.endpoint or "<unknown>"

        try:
            record_http_request(
                method=request.method,
                endpoint=endpoint,
                status_code=str(response.status_code),
                duration_seconds=duration,
            )
        except Exception:
            pass

        return response
