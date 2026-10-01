"""HTTPS deployments must enforce cookie and direct-peer trust boundaries."""

import pytest
from flask import Flask, session

from app_setup.security_middleware import setup_https_redirect, setup_security_headers


def app_for(monkeypatch: pytest.MonkeyPatch, *, proxy: str = "") -> Flask:
    monkeypatch.setenv("INKYPI_FORCE_HTTPS", "1")
    monkeypatch.setenv("INKYPI_TRUSTED_PROXIES", proxy)
    app = Flask(__name__)
    app.secret_key = "isolated-test-key"
    setup_https_redirect(app, dev_mode=False)
    setup_security_headers(app, dev_mode=False)

    @app.get("/session")
    def create_session() -> str:
        session["example"] = True
        return "ok"

    return app


def test_direct_forwarded_header_cannot_bypass_https(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = (
        app_for(monkeypatch)
        .test_client()
        .get("/session", headers={"X-Forwarded-Proto": "https"})
    )
    assert response.status_code == 301
    assert "Strict-Transport-Security" not in response.headers


def test_https_profile_sets_secure_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    response = (
        app_for(monkeypatch).test_client().get("/session", base_url="https://localhost")
    )
    assert response.status_code == 200
    assert "; Secure;" in response.headers["Set-Cookie"]


@pytest.mark.parametrize(
    "peer,proto,expected",
    [
        ("127.0.0.1", "https", 200),
        ("127.0.0.2", "https", 301),
        ("127.0.0.1", "http", 301),
        ("127.0.0.1", "https, http", 301),
        ("::1", "https", 200),
        ("not-an-ip", "https", 301),
    ],
)
def test_only_configured_direct_proxy_peers_are_trusted(
    monkeypatch: pytest.MonkeyPatch, peer: str, proto: str, expected: int
) -> None:
    response = (
        app_for(monkeypatch, proxy="127.0.0.1/32,::1/128")
        .test_client()
        .get(
            "/session",
            headers={
                "X-Forwarded-Proto": proto,
                "X-Forwarded-Host": "evil.test",
                "X-Forwarded-For": "127.0.0.1",
            },
            environ_overrides={"REMOTE_ADDR": peer},
        )
    )
    assert response.status_code == expected
    if expected == 200:
        assert "; Secure;" in response.headers["Set-Cookie"]
    else:
        assert response.location == "https://localhost/session"


def test_invalid_proxy_configuration_fails_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="INKYPI_TRUSTED_PROXIES"):
        app_for(monkeypatch, proxy="typo-proxy")


def test_https_redirect_precedes_auth_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INKYPI_FORCE_HTTPS", "1")
    monkeypatch.delenv("INKYPI_TRUSTED_PROXIES", raising=False)
    app = Flask(__name__)
    called = []

    @app.before_request
    def authentication() -> tuple[str, int]:
        called.append(True)
        return "authentication processed", 401

    setup_https_redirect(app, dev_mode=False)
    response = app.test_client().post("/login")
    assert response.status_code == 301
    assert called == []


@pytest.mark.parametrize("dev_mode", [False, True])
def test_default_lan_http_profile_remains_available(
    monkeypatch: pytest.MonkeyPatch, dev_mode: bool
) -> None:
    monkeypatch.delenv("INKYPI_FORCE_HTTPS", raising=False)
    monkeypatch.delenv("INKYPI_SECURE_COOKIES", raising=False)
    monkeypatch.delenv("INKYPI_TRUSTED_PROXIES", raising=False)
    app = Flask(__name__)
    app.secret_key = "isolated-test-key"
    setup_https_redirect(app, dev_mode=dev_mode)
    assert app.config["SESSION_COOKIE_SECURE"] is False


@pytest.mark.parametrize("network", ["0.0.0.0/0", "::/0"])
def test_unrestricted_proxy_network_is_rejected(
    monkeypatch: pytest.MonkeyPatch, network: str
) -> None:
    with pytest.raises(ValueError, match="INKYPI_TRUSTED_PROXIES"):
        app_for(monkeypatch, proxy=network)
