import importlib
import sys


def _reload_inkypi(monkeypatch, argv=None, env=None):
    if argv is None:
        argv = ["inkypi.py"]
    if env is None:
        env = {}

    for key in ["INKYPI_CSP", "INKYPI_CSP_REPORT_ONLY", "INKYPI_ENV", "FLASK_ENV"]:
        monkeypatch.delenv(key, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    monkeypatch.setattr(sys, "argv", argv)
    if "inkypi" in sys.modules:
        del sys.modules["inkypi"]
    import inkypi  # noqa: F401

    mod = importlib.reload(sys.modules["inkypi"])
    mod.main(argv[1:])
    return mod


def test_csp_enforcement_and_report_only(monkeypatch):
    mod = _reload_inkypi(monkeypatch)
    app = mod.app
    client = app.test_client()

    # Default report-only in env
    r = client.get("/healthz")
    assert ("Content-Security-Policy-Report-Only" in r.headers) or (
        "Content-Security-Policy" in r.headers
    )

    # Force enforcement header via env
    monkeypatch.setenv("INKYPI_CSP_REPORT_ONLY", "0")
    r2 = client.get("/healthz")
    assert "Content-Security-Policy" in r2.headers
    assert "Content-Security-Policy-Report-Only" not in r2.headers

    # Custom CSP value
    monkeypatch.setenv("INKYPI_CSP", "default-src 'none'")
    r3 = client.get("/healthz")
    header_name = "Content-Security-Policy"
    # The middleware appends report-uri to the custom value
    assert r3.headers.get(header_name, "").startswith("default-src 'none'")


def test_csp_nonce_present_and_unique_per_request(monkeypatch):
    """Each request generates a unique nonce that appears in the CSP header."""
    mod = _reload_inkypi(monkeypatch)
    app = mod.app
    client = app.test_client()

    monkeypatch.setenv("INKYPI_CSP_REPORT_ONLY", "0")

    r1 = client.get("/healthz")
    r2 = client.get("/healthz")

    csp1 = r1.headers.get("Content-Security-Policy", "")
    csp2 = r2.headers.get("Content-Security-Policy", "")

    # Both responses must carry a nonce in script-src.
    assert "nonce-" in csp1, f"nonce missing in CSP: {csp1}"
    assert "nonce-" in csp2, f"nonce missing in CSP: {csp2}"

    # Nonces must differ between requests (collision probability ~2^-96).
    import re

    def _extract_nonce(csp):
        m = re.search(r"nonce-([A-Za-z0-9_=-]+)", csp)
        return m.group(1) if m else None

    assert _extract_nonce(csp1) != _extract_nonce(csp2), (
        "CSP nonce must be unique per request"
    )


def test_csp_nonce_not_injected_when_custom_csp_set(monkeypatch):
    """Custom INKYPI_CSP values are used verbatim — no nonce is injected."""
    mod = _reload_inkypi(monkeypatch, env={"INKYPI_CSP_REPORT_ONLY": "0"})
    app = mod.app
    client = app.test_client()

    monkeypatch.setenv("INKYPI_CSP", "default-src 'none'")
    r = client.get("/healthz")
    csp = r.headers.get("Content-Security-Policy", "")
    # The custom value starts verbatim (report-uri may be appended).
    assert csp.startswith("default-src 'none'"), f"Unexpected CSP: {csp}"
    # No nonce should appear in a custom policy (operator's responsibility).
    assert "nonce-" not in csp


def test_hsts_only_under_https_or_forward_proto(monkeypatch):
    mod = _reload_inkypi(monkeypatch)
    app = mod.app
    client = app.test_client()

    # No HSTS for plain HTTP
    r = client.get("/healthz")
    assert "Strict-Transport-Security" not in r.headers

    # HSTS when HTTPS
    r2 = client.get("/healthz", base_url="https://localhost")
    assert "Strict-Transport-Security" in r2.headers

    # HSTS when forwarded proto HTTPS
    r3 = client.get("/healthz", headers={"X-Forwarded-Proto": "https"})
    assert "Strict-Transport-Security" in r3.headers
