# pyright: reportMissingImports=false
"""Always-on Host header allow-list (grade report E1, DNS rebinding).

A malicious page can rebind its own domain to the Pi's LAN address and become
same-origin with the InkyPi UI. The browser still sends the attacker's domain
in ``Host``, so every request whose Host does not name this device must be
rejected with 400 before any route (or CSRF token issuance) runs.
"""

from __future__ import annotations

from typing import Any

import pytest

from app_setup import security_middleware as sm

_CSP_REPORT = {"csp-report": {"violated-directive": "img-src", "blocked-uri": "x"}}


@pytest.fixture(autouse=True)
def _private_csp_report_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    # The CSP-report endpoint keeps a module-level per-IP limiter; give these
    # tests their own so the POSTs below don't throttle tests that run later.
    from blueprints import csp_report
    from utils.rate_limiter import SlidingWindowLimiter

    monkeypatch.setattr(
        csp_report, "_csp_report_limiter", SlidingWindowLimiter(100_000, 60)
    )


@pytest.fixture()
def fixed_hostname(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(sm.socket, "gethostname", lambda: "Kitchen-Frame")
    monkeypatch.delenv("INKYPI_ALLOWED_HOSTS", raising=False)
    return "kitchen-frame"


@pytest.mark.parametrize("host", ["evil.example", "evil.example:80", "inkypi.evil"])
def test_foreign_host_rejected_on_page(
    client: Any, fixed_hostname: str, host: str
) -> None:
    resp = client.get("/settings", headers={"Host": host})
    assert resp.status_code == 400


def test_foreign_host_rejected_on_post_api(client: Any, fixed_hostname: str) -> None:
    resp = client.post(
        "/api/csp-report", json=_CSP_REPORT, headers={"Host": "evil.example"}
    )
    assert resp.status_code == 400


def test_foreign_host_rejected_on_healthz(client: Any, fixed_hostname: str) -> None:
    # Boot/systemd probes curl 127.0.0.1, so nothing needs an exemption.
    assert client.get("/healthz", headers={"Host": "evil.example"}).status_code == 400
    assert client.get("/healthz", headers={"Host": "127.0.0.1:80"}).status_code == 200


@pytest.mark.parametrize(
    "host",
    [
        "localhost",
        "localhost:8080",
        "LOCALHOST",
        "127.0.0.1",
        "192.168.1.42:80",
        "10.0.0.5:8080",
        "[::1]",
        "[::1]:8080",
        "[fe80::1]:5000",
        "inkypi",
        "inkypi.local",
        "InkyPi.Local.",
        "kitchen-frame",
        "Kitchen-Frame:8080",
        "kitchen-frame.local",
        "KITCHEN-FRAME.LOCAL:80",
    ],
)
def test_device_hosts_accepted(client: Any, fixed_hostname: str, host: str) -> None:
    resp = client.get("/settings", headers={"Host": host})
    assert resp.status_code != 400, host
    post = client.post("/api/csp-report", json=_CSP_REPORT, headers={"Host": host})
    assert post.status_code != 400, host


def test_allowed_hosts_env_is_additive(
    client: Any, fixed_hostname: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INKYPI_ALLOWED_HOSTS", " Frame.Example.COM , other.lan ")
    for host in ("frame.example.com", "other.lan:8443", "localhost", "kitchen-frame"):
        assert client.get("/settings", headers={"Host": host}).status_code != 400
    assert client.get("/settings", headers={"Host": "evil.example"}).status_code == 400


def test_default_test_client_host_accepted(client: Any) -> None:
    # Flask's test client sends ``Host: localhost``.
    assert client.get("/settings").status_code == 200


@pytest.mark.parametrize(
    "raw",
    ["", "[::1", "[::1]x", "localhost:abc", "evil.example", "127.0.0.1.evil"],
)
def test_is_allowed_host_rejects_malformed(fixed_hostname: str, raw: str) -> None:
    assert sm._is_allowed_host(raw) is False


def test_host_check_runs_first(flask_app: Any) -> None:
    hooks = flask_app.before_request_funcs[None]
    assert hooks[0].__name__ == "_validate_host"
