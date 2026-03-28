# ---------------------------------------------------------------------------
# Health endpoints
# ---------------------------------------------------------------------------

def test_health_endpoints(client):
    # Liveness is always OK
    r = client.get("/healthz")
    assert r.status_code == 200
    # Readiness reflects running state or web-only
    r2 = client.get("/readyz")
    assert r2.status_code in (200, 503)


# ---------------------------------------------------------------------------
# Content Security Policy headers
# ---------------------------------------------------------------------------

def test_csp_report_only_header(client, monkeypatch):
    # Ensure default report-only is applied
    resp = client.get("/")
    assert resp.status_code == 200
    # Either CSP-Report-Only or CSP present
    ro = resp.headers.get("Content-Security-Policy-Report-Only")
    csp = resp.headers.get("Content-Security-Policy")
    assert ro or csp


def test_csp_header_enforced_when_report_only_disabled(client, monkeypatch):
    # Disable report-only mode to enforce CSP header
    monkeypatch.setenv("INKYPI_CSP_REPORT_ONLY", "0")
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Content-Security-Policy" in resp.headers
    assert "Content-Security-Policy-Report-Only" not in resp.headers
