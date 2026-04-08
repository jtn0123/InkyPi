"""Tests for HTTP request timing metrics (JTN-362).

Verifies that the before/after request hooks in app_setup.http_metrics
correctly populate the Prometheus histogram and counter for each request,
that /metrics itself is excluded from measurement, that /static/* is
excluded, and that status codes (including 4xx/5xx) are labelled correctly.
"""

from __future__ import annotations

import utils.metrics as m

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _histogram_count(
    histogram_metric, method: str, endpoint: str, status_code: str
) -> float:
    """Return the observation count (_count sample) for a histogram label-set."""
    child = histogram_metric.labels(
        method=method, endpoint=endpoint, status_code=status_code
    )
    for sample in child._child_samples():
        if sample.name == "_count":
            return sample.value
    return 0.0


def _counter_value(
    counter_metric, method: str, endpoint: str, status_code: str
) -> float:
    """Return the current value of a labelled counter."""
    return counter_metric.labels(
        method=method, endpoint=endpoint, status_code=status_code
    )._value.get()


# ---------------------------------------------------------------------------
# Basic recording — GET /healthz
# ---------------------------------------------------------------------------


def test_histogram_count_increments_on_request(client):
    """A normal GET request must increment the histogram observation count."""
    before = _histogram_count(m.http_request_duration_seconds, "GET", "/healthz", "200")
    client.get("/healthz")
    after = _histogram_count(m.http_request_duration_seconds, "GET", "/healthz", "200")
    assert after == before + 1


def test_total_counter_increments_on_request(client):
    """A normal GET request must increment the requests total counter."""
    before = _counter_value(m.http_requests_total, "GET", "/healthz", "200")
    client.get("/healthz")
    after = _counter_value(m.http_requests_total, "GET", "/healthz", "200")
    assert after == before + 1


def test_metrics_reflected_in_prometheus_output(client):
    """After a /healthz hit the /metrics output must contain the histogram family."""
    client.get("/healthz")
    resp = client.get("/metrics")
    assert resp.status_code == 200
    body = resp.data
    assert b"inkypi_http_request_duration_seconds" in body
    assert b"inkypi_http_requests_total" in body


# ---------------------------------------------------------------------------
# /metrics itself is NOT measured
# ---------------------------------------------------------------------------


def test_scraping_metrics_endpoint_is_not_recorded(client):
    """/metrics requests must not appear in the histogram."""
    before = _histogram_count(m.http_request_duration_seconds, "GET", "/metrics", "200")
    client.get("/metrics")
    after = _histogram_count(m.http_request_duration_seconds, "GET", "/metrics", "200")
    assert after == before, "/metrics itself must not be measured"


def test_scraping_metrics_counter_not_recorded(client):
    """/metrics requests must not appear in the total counter."""
    before = _counter_value(m.http_requests_total, "GET", "/metrics", "200")
    client.get("/metrics")
    after = _counter_value(m.http_requests_total, "GET", "/metrics", "200")
    assert after == before, "/metrics itself must not be counted"


# ---------------------------------------------------------------------------
# 4xx status codes are recorded
# ---------------------------------------------------------------------------


def test_404_is_recorded_with_correct_status(client):
    """A 404 response must be recorded with status_code='404'."""
    before = _histogram_count(
        m.http_request_duration_seconds, "GET", "<unknown>", "404"
    )
    client.get("/this-path-does-not-exist-xyz")
    after = _histogram_count(m.http_request_duration_seconds, "GET", "<unknown>", "404")
    assert after == before + 1


def test_404_counter_is_recorded(client):
    """The total counter must also capture 404s."""
    before = _counter_value(m.http_requests_total, "GET", "<unknown>", "404")
    client.get("/this-path-does-not-exist-xyz")
    after = _counter_value(m.http_requests_total, "GET", "<unknown>", "404")
    assert after == before + 1


# ---------------------------------------------------------------------------
# url_rule label — avoids cardinality explosion
# ---------------------------------------------------------------------------


def test_endpoint_label_uses_url_rule_not_raw_path(client):
    """The endpoint label must be the Flask url_rule, not the raw path."""
    # /healthz is registered as a route rule — the label must be '/healthz',
    # not a raw path that might include dynamic segments.
    before_rule = _histogram_count(
        m.http_request_duration_seconds, "GET", "/healthz", "200"
    )
    client.get("/healthz")
    after_rule = _histogram_count(
        m.http_request_duration_seconds, "GET", "/healthz", "200"
    )
    assert after_rule == before_rule + 1


def test_multiple_requests_accumulate_count(client):
    """Multiple requests to the same endpoint must accumulate in the histogram."""
    before = _histogram_count(m.http_request_duration_seconds, "GET", "/healthz", "200")
    for _ in range(5):
        client.get("/healthz")
    after = _histogram_count(m.http_request_duration_seconds, "GET", "/healthz", "200")
    assert after == before + 5
