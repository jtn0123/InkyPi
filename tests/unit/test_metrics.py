"""Tests for the Prometheus /metrics endpoint (JTN-334)."""

from __future__ import annotations

import pytest
from prometheus_client import CollectorRegistry, Counter, Gauge  # noqa: F401

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_registry():
    """Return a brand-new CollectorRegistry with the five InkyPi metrics."""
    reg = CollectorRegistry(auto_describe=True)
    Counter(
        "inkypi_refreshes_total",
        "Total refresh attempts",
        labelnames=["status"],
        registry=reg,
    )
    Gauge(
        "inkypi_last_successful_refresh_timestamp_seconds",
        "Last successful refresh timestamp",
        registry=reg,
    )
    Counter(
        "inkypi_plugin_failures_total",
        "Plugin failures",
        labelnames=["plugin"],
        registry=reg,
    )
    Gauge(
        "inkypi_plugin_circuit_breaker_open",
        "Circuit breaker open flag",
        labelnames=["plugin"],
        registry=reg,
    )
    Gauge(
        "inkypi_uptime_seconds",
        "Process uptime",
        registry=reg,
    )
    return reg


# ---------------------------------------------------------------------------
# /metrics endpoint — HTTP contract
# ---------------------------------------------------------------------------


def test_metrics_endpoint_returns_200(client):
    resp = client.get("/metrics")
    assert resp.status_code == 200


def test_metrics_endpoint_content_type(client):
    resp = client.get("/metrics")
    ct = resp.content_type
    assert ct.startswith("text/plain")
    assert "version=0.0.4" in ct


def test_metrics_endpoint_no_auth_required(client):
    """Scraping /metrics must succeed without any session or API key."""
    resp = client.get("/metrics")
    # Must NOT redirect to a login page
    assert resp.status_code == 200
    assert b"inkypi_" in resp.data


# ---------------------------------------------------------------------------
# Metric names present in the output
# ---------------------------------------------------------------------------


_EXPECTED_METRIC_NAMES = [
    b"inkypi_refreshes_total",
    b"inkypi_last_successful_refresh_timestamp_seconds",
    b"inkypi_plugin_failures_total",
    b"inkypi_plugin_circuit_breaker_open",
    b"inkypi_uptime_seconds",
]


@pytest.mark.parametrize("metric_name", _EXPECTED_METRIC_NAMES)
def test_metrics_body_contains_metric_name(client, metric_name):
    resp = client.get("/metrics")
    assert metric_name in resp.data, f"{metric_name!r} not found in /metrics output"


# ---------------------------------------------------------------------------
# Counter increments are reflected in output
# ---------------------------------------------------------------------------


def test_refresh_success_counter_increments(client, monkeypatch):
    """record_refresh_success() must bump inkypi_refreshes_total{status='success'}."""
    import utils.metrics as m

    # Capture the initial value
    before = m.refreshes_total.labels(status="success")._value.get()
    m.record_refresh_success()
    after = m.refreshes_total.labels(status="success")._value.get()
    assert after == before + 1

    resp = client.get("/metrics")
    assert b'inkypi_refreshes_total{status="success"}' in resp.data


def test_refresh_failure_counter_increments(client):
    """record_refresh_failure() must bump both the total and plugin counters."""
    import utils.metrics as m

    before_total = m.refreshes_total.labels(status="failure")._value.get()
    before_plugin = m.plugin_failures_total.labels(plugin="test_plugin")._value.get()

    m.record_refresh_failure("test_plugin")

    assert m.refreshes_total.labels(status="failure")._value.get() == before_total + 1
    assert (
        m.plugin_failures_total.labels(plugin="test_plugin")._value.get()
        == before_plugin + 1
    )


def test_plugin_failure_reflected_in_endpoint(client):
    """After a simulated plugin failure the body must contain the plugin label."""
    import utils.metrics as m

    m.record_refresh_failure("my_plugin")
    resp = client.get("/metrics")
    assert b"my_plugin" in resp.data


# ---------------------------------------------------------------------------
# Circuit-breaker gauge
# ---------------------------------------------------------------------------


def test_circuit_breaker_open_sets_gauge_to_1(client):
    import utils.metrics as m

    m.set_circuit_breaker_open("demo_plugin", True)
    val = m.plugin_circuit_breaker_open.labels(plugin="demo_plugin")._value.get()
    assert val == 1.0


def test_circuit_breaker_close_sets_gauge_to_0(client):
    import utils.metrics as m

    m.set_circuit_breaker_open("demo_plugin", True)
    m.set_circuit_breaker_open("demo_plugin", False)
    val = m.plugin_circuit_breaker_open.labels(plugin="demo_plugin")._value.get()
    assert val == 0.0


# ---------------------------------------------------------------------------
# Uptime gauge is positive
# ---------------------------------------------------------------------------


def test_uptime_gauge_is_positive(client):
    import utils.metrics as m

    m.update_uptime()
    val = m.uptime_seconds._value.get()
    assert val > 0


# ---------------------------------------------------------------------------
# Custom registry (isolation — metrics module helper)
# ---------------------------------------------------------------------------


def test_fresh_registry_has_all_five_metrics():
    """Sanity-check the helper used in isolation tests."""
    from prometheus_client.exposition import generate_latest

    reg = _fresh_registry()
    output = generate_latest(reg).decode()
    for name in (
        "inkypi_refreshes_total",
        "inkypi_last_successful_refresh_timestamp_seconds",
        "inkypi_plugin_failures_total",
        "inkypi_plugin_circuit_breaker_open",
        "inkypi_uptime_seconds",
    ):
        assert name in output, f"{name!r} missing from fresh registry output"
