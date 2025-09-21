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
    assert ("Content-Security-Policy-Report-Only" in r.headers) or ("Content-Security-Policy" in r.headers)

    # Force enforcement header via env
    monkeypatch.setenv("INKYPI_CSP_REPORT_ONLY", "0")
    r2 = client.get("/healthz")
    assert "Content-Security-Policy" in r2.headers
    assert "Content-Security-Policy-Report-Only" not in r2.headers

    # Custom CSP value
    monkeypatch.setenv("INKYPI_CSP", "default-src 'none'")
    r3 = client.get("/healthz")
    header_name = "Content-Security-Policy"
    assert r3.headers.get(header_name) == "default-src 'none'"


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

