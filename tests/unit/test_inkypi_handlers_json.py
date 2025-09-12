import importlib
import sys
from typing import Any

import pytest
from flask import abort


def _reload_inkypi(monkeypatch, argv=None, env=None):
    if argv is None:
        argv = ["inkypi.py"]
    if env is None:
        env = {}

    # Reset influencing env
    for key in [
        "INKYPI_ENV",
        "FLASK_ENV",
        "INKYPI_CONFIG_FILE",
        "SECRET_KEY",
        "PROJECT_DIR",
        "INKYPI_NO_REFRESH",
        "INKYPI_CSP",
        "INKYPI_CSP_REPORT_ONLY",
    ]:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    monkeypatch.setattr(sys, "argv", argv)

    if "inkypi" in sys.modules:
        del sys.modules["inkypi"]

    import inkypi  # noqa: F401
    mod = importlib.reload(sys.modules["inkypi"])
    mod.main(argv[1:])
    return mod


def _register_test_routes(app):
    from utils.http_utils import APIError

    @app.route("/cause_api_error")
    def cause_api_error():
        raise APIError("boom", status=418, code="X", details={"a": 1})

    @app.route("/cause_bad_request")
    def cause_bad_request():
        return abort(400)

    @app.route("/cause_unsupported")
    def cause_unsupported():
        return abort(415)

    @app.route("/cause_exception")
    def cause_exception():
        raise RuntimeError("explode")


def test_error_handlers_json_and_html(monkeypatch):
    mod = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env={})
    app = getattr(mod, "app", None)
    assert app is not None

    _register_test_routes(app)
    client = app.test_client()

    # JSON Accept should yield JSON bodies
    r = client.get("/cause_api_error", headers={"Accept": "application/json"})
    assert r.status_code == 418
    assert r.is_json and r.get_json().get("error") == "boom"

    r = client.get("/cause_bad_request", headers={"Accept": "application/json"})
    assert r.status_code == 400
    assert r.is_json and r.get_json().get("error") == "Bad request"

    r = client.get("/cause_unsupported", headers={"Accept": "application/json"})
    assert r.status_code == 415
    assert r.is_json and r.get_json().get("error") == "Unsupported media type"

    r = client.get("/cause_exception", headers={"Accept": "application/json"})
    assert r.status_code == 500
    assert r.is_json and r.get_json().get("error")

    # HTML Accept should yield plain text bodies
    r = client.get("/cause_bad_request", headers={"Accept": "text/html"})
    assert r.status_code == 400
    assert b"Bad request" in r.data

    r = client.get("/cause_unsupported", headers={"Accept": "text/html"})
    assert r.status_code == 415
    assert b"Unsupported media type" in r.data

    r = client.get("/cause_exception", headers={"Accept": "text/html"})
    assert r.status_code == 500
    assert b"Internal Server Error" in r.data


def test_readyz_states(monkeypatch):
    mod = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env={})
    app = getattr(mod, "app", None)
    assert app is not None
    client = app.test_client()

    # web-only branch
    app.config["WEB_ONLY"] = True
    r = client.get("/readyz")
    assert r.status_code == 200 and b"ready:web-only" in r.data

    # running branch
    app.config["WEB_ONLY"] = False
    class _RT:
        running: bool = True

    app.config["REFRESH_TASK"] = _RT()
    r = client.get("/readyz")
    assert r.status_code == 200 and b"ready" in r.data

    # not-ready branch
    app.config["REFRESH_TASK"].running = False
    r = client.get("/readyz")
    assert r.status_code == 503 and b"not-ready" in r.data


def test_csp_headers_default_and_overrides(monkeypatch):
    # Default: report-only header is set
    mod = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env={})
    app = getattr(mod, "app", None)
    assert app is not None
    client = app.test_client()

    r = client.get("/healthz")
    # Default is report-only
    assert (
        "Content-Security-Policy-Report-Only" in r.headers
    ), "CSP report-only header missing"
    assert "default-src" in r.headers["Content-Security-Policy-Report-Only"]

    # Force enforcement header via env
    monkeypatch.setenv("INKYPI_CSP_REPORT_ONLY", "0")
    r2 = client.get("/healthz")
    assert "Content-Security-Policy" in r2.headers
    assert "Content-Security-Policy-Report-Only" not in r2.headers

    # Custom policy value
    monkeypatch.setenv("INKYPI_CSP", "default-src 'none'")
    r3 = client.get("/healthz")
    header_name = (
        "Content-Security-Policy"
        if "Content-Security-Policy" in r3.headers
        else "Content-Security-Policy-Report-Only"
    )
    assert r3.headers[header_name] == "default-src 'none'"


