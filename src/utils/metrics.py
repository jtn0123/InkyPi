"""Prometheus metrics registry for InkyPi (JTN-334).

All metric instances live here so that:
  - updates are funnelled through helpers (no scattered inc() calls),
  - tests can clear the registry between runs,
  - the /metrics blueprint imports a single well-known object.

Usage
-----
from utils.metrics import record_refresh_success, record_plugin_failure, ...
"""

from __future__ import annotations

import time

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

# ---------------------------------------------------------------------------
# Registry — one per process; tests can create fresh instances as needed.
# ---------------------------------------------------------------------------

metrics_registry = CollectorRegistry(auto_describe=True)

# ---------------------------------------------------------------------------
# Metric definitions
# ---------------------------------------------------------------------------

refreshes_total = Counter(
    "inkypi_refreshes_total",
    "Total number of display refresh attempts",
    labelnames=["status"],
    registry=metrics_registry,
)

last_successful_refresh_timestamp = Gauge(
    "inkypi_last_successful_refresh_timestamp_seconds",
    "Unix timestamp of the last successful display refresh",
    registry=metrics_registry,
)

plugin_failures_total = Counter(
    "inkypi_plugin_failures_total",
    "Total number of plugin failures by plugin id",
    labelnames=["plugin"],
    registry=metrics_registry,
)

plugin_circuit_breaker_open = Gauge(
    "inkypi_plugin_circuit_breaker_open",
    "1 if the plugin circuit-breaker is open (plugin paused), 0 if closed",
    labelnames=["plugin"],
    registry=metrics_registry,
)

uptime_seconds = Gauge(
    "inkypi_uptime_seconds",
    "Seconds since the InkyPi process started",
    registry=metrics_registry,
)

_HTTP_DURATION_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10)

http_request_duration_seconds = Histogram(
    "inkypi_http_request_duration_seconds",
    "Per-endpoint HTTP request latency",
    labelnames=["method", "endpoint", "status_code"],
    buckets=_HTTP_DURATION_BUCKETS,
    registry=metrics_registry,
)

http_requests_total = Counter(
    "inkypi_http_requests_total",
    "Total HTTP requests by method, endpoint, and status code",
    labelnames=["method", "endpoint", "status_code"],
    registry=metrics_registry,
)

# Record the process-start time so we can compute uptime on demand.
_process_start_time: float = time.monotonic()


# ---------------------------------------------------------------------------
# Helper functions — the only public API callers should use
# ---------------------------------------------------------------------------


def record_refresh_success() -> None:
    """Increment refresh counter for a successful refresh and set the timestamp."""
    refreshes_total.labels(status="success").inc()
    last_successful_refresh_timestamp.set(time.time())


def record_refresh_failure(plugin_name: str) -> None:
    """Increment refresh and plugin-failure counters for a failed refresh."""
    refreshes_total.labels(status="failure").inc()
    plugin_failures_total.labels(plugin=plugin_name).inc()


def set_circuit_breaker_open(plugin_name: str, is_open: bool) -> None:
    """Set the circuit-breaker gauge for *plugin_name*.

    Pass ``is_open=True`` when the breaker trips (plugin paused),
    ``is_open=False`` when it resets (plugin recovered).
    """
    plugin_circuit_breaker_open.labels(plugin=plugin_name).set(1 if is_open else 0)


def update_uptime() -> None:
    """Refresh the uptime gauge. Called by the /metrics handler before serialising."""
    uptime_seconds.set(time.monotonic() - _process_start_time)


def record_http_request(
    method: str, endpoint: str, status_code: str, duration_seconds: float
) -> None:
    """Record a single HTTP request in the duration histogram and total counter."""
    labels = {"method": method, "endpoint": endpoint, "status_code": status_code}
    http_request_duration_seconds.labels(**labels).observe(duration_seconds)
    http_requests_total.labels(**labels).inc()
