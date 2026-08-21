# pyright: reportMissingImports=false
"""Tests for the read-only bearer token auth path (JTN-477).

Coverage:
- Token unset → only PIN session grants access to protected routes
- Token set → GET on allowlist with correct Bearer token returns 200 (no session)
- Token set → wrong token value → 401 redirect (goes to login)
- Token set → correct token on non-allowlist path → still requires PIN
- Token set → correct token on allowlist but POST method → still requires PIN
- Token works on GET /api/screenshot (allowlist)
- Existing PIN auth tests are not broken
"""

from __future__ import annotations

import importlib
import os
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient
from jinja2 import ChoiceLoader, FileSystemLoader

SRC_ABS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))

TOKEN = "super-secret-monitoring-token-abc123"


def _make_app(
    monkeypatch: pytest.MonkeyPatch,
    *,
    pin: str | None = "s3cr3t",
    token: str | None = None,
) -> Flask:
    """Build a minimal Flask app with auth (PIN + optional token) wired up."""
    if pin:
        monkeypatch.setenv("INKYPI_AUTH_PIN", pin)
    else:
        monkeypatch.delenv("INKYPI_AUTH_PIN", raising=False)

    if token:
        monkeypatch.setenv("INKYPI_READONLY_TOKEN", token)
    else:
        monkeypatch.delenv("INKYPI_READONLY_TOKEN", raising=False)

    import app_setup.auth as auth_mod

    importlib.reload(auth_mod)
    import blueprints.auth as auth_bp_mod

    importlib.reload(auth_bp_mod)

    app = Flask(__name__)
    app.secret_key = "test-secret-key"
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    template_dirs = [
        os.path.join(SRC_ABS, "templates"),
        os.path.join(SRC_ABS, "plugins"),
    ]
    app.jinja_loader = ChoiceLoader([FileSystemLoader(d) for d in template_dirs])

    from blueprints.auth import auth_bp

    app.register_blueprint(auth_bp)

    # Stub out the allowlisted endpoints
    @app.route("/api/health")
    def api_health() -> Any:
        return ("ok", 200)

    @app.route("/api/version/info")
    def api_version_info() -> Any:
        return ("version", 200)

    @app.route("/api/uptime")
    def api_uptime() -> Any:
        return ("uptime", 200)

    @app.route("/api/screenshot", methods=["GET", "POST"])
    def api_screenshot() -> Any:
        return ("screenshot", 200)

    @app.route("/metrics")
    def metrics() -> Any:
        return ("metrics", 200)

    @app.route("/api/stats")
    def api_stats() -> Any:
        return ("stats", 200)

    # A mutating endpoint NOT on the allowlist
    @app.route("/api/settings", methods=["GET", "POST"])
    def api_settings() -> Any:
        return ("settings", 200)

    # Home page (protected, not on allowlist)
    @app.route("/")
    def index() -> Any:
        return ("home", 200)

    class _FakeConfig:
        def get_config(self, key: Any, default: Any = None) -> Any:
            return default

    auth_mod.init_auth(app, _FakeConfig())

    return app


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Token NOT configured
# ---------------------------------------------------------------------------


class TestTokenUnset:
    @pytest.fixture()
    def app(self, monkeypatch: pytest.MonkeyPatch) -> Any:
        return _make_app(monkeypatch, pin="s3cr3t", token=None)

    @pytest.fixture()
    def client(self, app: Flask) -> Any:
        return app.test_client()

    def test_allowlist_without_token_requires_pin_session(
        self, client: FlaskClient
    ) -> None:
        """Without a token configured, allowlist paths require PIN auth."""
        # /api/health is always exempt — use a different allowlist path
        resp = client.get("/api/version/info")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_bearer_header_without_token_configured_is_ignored(
        self, client: FlaskClient
    ) -> None:
        """Sending a Bearer header when no token is configured doesn't bypass auth."""
        resp = client.get("/api/uptime", headers=_bearer(TOKEN))
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_pin_session_still_grants_access(self, client: FlaskClient) -> None:
        with client.session_transaction() as sess:
            sess["authed"] = True
        resp = client.get("/api/version/info")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Token configured — happy path
# ---------------------------------------------------------------------------


class TestTokenSet:
    @pytest.fixture()
    def app(self, monkeypatch: pytest.MonkeyPatch) -> Any:
        return _make_app(monkeypatch, pin="s3cr3t", token=TOKEN)

    @pytest.fixture()
    def client(self, app: Flask) -> Any:
        return app.test_client()

    def test_correct_token_on_allowlist_returns_200(self, client: FlaskClient) -> None:
        resp = client.get("/api/version/info", headers=_bearer(TOKEN))
        assert resp.status_code == 200

    def test_correct_token_on_uptime_returns_200(self, client: FlaskClient) -> None:
        resp = client.get("/api/uptime", headers=_bearer(TOKEN))
        assert resp.status_code == 200

    def test_correct_token_on_metrics_returns_200(self, client: FlaskClient) -> None:
        resp = client.get("/metrics", headers=_bearer(TOKEN))
        assert resp.status_code == 200

    def test_correct_token_on_stats_returns_200(self, client: FlaskClient) -> None:
        resp = client.get("/api/stats", headers=_bearer(TOKEN))
        assert resp.status_code == 200

    def test_correct_token_on_screenshot_get_returns_200(
        self, client: FlaskClient
    ) -> None:
        resp = client.get("/api/screenshot", headers=_bearer(TOKEN))
        assert resp.status_code == 200

    def test_wrong_token_on_allowlist_redirects_to_login(
        self, client: FlaskClient
    ) -> None:
        resp = client.get("/api/version/info", headers=_bearer("bad-token"))
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_no_bearer_header_on_allowlist_redirects_to_login(
        self, client: FlaskClient
    ) -> None:
        resp = client.get("/api/version/info")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_correct_token_on_non_allowlist_path_redirects_to_login(
        self, client: FlaskClient
    ) -> None:
        """Token is only valid on the allowlist — other paths still require PIN."""
        resp = client.get("/api/settings", headers=_bearer(TOKEN))
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_correct_token_on_home_redirects_to_login(
        self, client: FlaskClient
    ) -> None:
        resp = client.get("/", headers=_bearer(TOKEN))
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_correct_token_post_screenshot_redirects_to_login(
        self, client: FlaskClient
    ) -> None:
        """Mutating (POST) requests are rejected even on an allowlist path."""
        resp = client.post("/api/screenshot", headers=_bearer(TOKEN))
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_correct_token_post_settings_redirects_to_login(
        self, client: FlaskClient
    ) -> None:
        resp = client.post("/api/settings", headers=_bearer(TOKEN))
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_pin_session_still_works_with_token_configured(
        self, client: FlaskClient
    ) -> None:
        """Enabling the token doesn't break existing PIN session auth."""
        with client.session_transaction() as sess:
            sess["authed"] = True
        resp = client.get("/")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Token configured, PIN disabled
# ---------------------------------------------------------------------------


class TestTokenSetNoPIN:
    """Token should work even when PIN auth is not configured."""

    @pytest.fixture()
    def app(self, monkeypatch: pytest.MonkeyPatch) -> Any:
        return _make_app(monkeypatch, pin=None, token=TOKEN)

    @pytest.fixture()
    def client(self, app: Flask) -> Any:
        return app.test_client()

    def test_no_pin_auth_home_accessible_without_auth(
        self, client: FlaskClient
    ) -> None:
        """When PIN is disabled, unprotected routes are open to everyone."""
        resp = client.get("/")
        assert resp.status_code == 200

    def test_token_stored_in_app_config(self, app: Flask) -> None:
        """The token hash is stored even when PIN auth is not enabled."""
        import hashlib

        expected = hashlib.sha256(TOKEN.encode()).hexdigest()
        assert app.config.get("READONLY_TOKEN_HASH") == expected
