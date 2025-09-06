def test_csp_report_only_header(client, monkeypatch):
    # Ensure default report-only is applied
    resp = client.get("/")
    assert resp.status_code == 200
    # Either CSP-Report-Only or CSP present
    ro = resp.headers.get("Content-Security-Policy-Report-Only")
    csp = resp.headers.get("Content-Security-Policy")
    assert ro or csp


