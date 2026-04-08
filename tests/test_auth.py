# pyright: reportMissingImports=false
"""Tests for optional PIN authentication (JTN-286).

Coverage:
- Auth disabled when INKYPI_AUTH_PIN is not set
- Auth enabled: unauthenticated request to / redirects to /login
- Correct PIN → session authed, redirect to /
- Wrong PIN → login page re-rendered with error
- Rate-limit lockout after 5 failed attempts
- Exempt paths (/sw.js, /static/*, /api/health) accessible without auth
- /logout clears session and redirects to /login
"""

from __future__ import annotations

import os
import time

import pytest
from flask import Flask
from jinja2 import ChoiceLoader, FileSystemLoader

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SRC_ABS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))


def _make_auth_app(pin: str | None = None, monkeypatch=None) -> Flask:
    """Build a minimal Flask app with auth wired up.

    If *pin* is given it is set as INKYPI_AUTH_PIN.
    """
    if monkeypatch is not None and pin is not None:
        monkeypatch.setenv("INKYPI_AUTH_PIN", pin)
    elif monkeypatch is not None:
        monkeypatch.delenv("INKYPI_AUTH_PIN", raising=False)

    # Fresh import context so module-level _SCRYPT_SALT is consistent
    import importlib

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

    # Register auth blueprint
    from blueprints.auth import auth_bp

    app.register_blueprint(auth_bp)

    # A trivial protected route
    @app.route("/")
    def index():
        return ("home", 200)

    @app.route("/api/health")
    def api_health():
        return ("ok", 200)

    @app.route("/sw.js")
    def sw():
        return ("sw", 200)

    @app.route("/static/test.css")
    def static_css():
        return ("css", 200)

    # Provide a CSRF token in the session for POST requests
    @app.context_processor
    def _inject_csrf():
        import secrets as _s

        from flask import session as _sess

        def _csrf():
            if "_csrf_token" not in _sess:
                _sess["_csrf_token"] = _s.token_hex(32)
            return _sess["_csrf_token"]

        return {"csrf_token": _csrf}

    # Wire auth (reads INKYPI_AUTH_PIN from env, which monkeypatch already set)
    class _FakeConfig:
        def get_config(self, key, default=None):
            return default

    auth_mod.init_auth(app, _FakeConfig())

    return app


def _get_csrf(client) -> str:
    """Return a fresh CSRF token by hitting /login and reading the session."""
    import secrets

    with client.session_transaction() as sess:
        token = secrets.token_hex(32)
        sess["_csrf_token"] = token
    return token


# ---------------------------------------------------------------------------
# Tests — auth DISABLED
# ---------------------------------------------------------------------------


class TestAuthDisabled:
    @pytest.fixture()
    def app(self, monkeypatch):
        return _make_auth_app(pin=None, monkeypatch=monkeypatch)

    @pytest.fixture()
    def client(self, app):
        return app.test_client()

    def test_home_accessible_without_login(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_login_route_still_works(self, client):
        resp = client.get("/login")
        assert resp.status_code == 200

    def test_static_accessible(self, client):
        resp = client.get("/static/test.css")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Tests — auth ENABLED
# ---------------------------------------------------------------------------


class TestAuthEnabled:
    PIN = "s3cr3t"

    @pytest.fixture()
    def app(self, monkeypatch):
        return _make_auth_app(pin=self.PIN, monkeypatch=monkeypatch)

    @pytest.fixture()
    def client(self, app):
        return app.test_client()

    # ------------------------------------------------------------------
    # Redirect enforcement
    # ------------------------------------------------------------------

    def test_unauthenticated_home_redirects_to_login(self, client):
        resp = client.get("/")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_authenticated_home_accessible(self, client):
        with client.session_transaction() as sess:
            sess["authed"] = True
        resp = client.get("/")
        assert resp.status_code == 200

    # ------------------------------------------------------------------
    # Exempt paths
    # ------------------------------------------------------------------

    def test_login_page_exempt(self, client):
        resp = client.get("/login")
        assert resp.status_code == 200

    def test_logout_exempt(self, client):
        # /logout redirects to /login — not blocked by auth guard
        resp = client.get("/logout")
        assert resp.status_code == 302

    def test_sw_js_exempt(self, client):
        resp = client.get("/sw.js")
        assert resp.status_code == 200

    def test_static_exempt(self, client):
        resp = client.get("/static/test.css")
        assert resp.status_code == 200

    def test_api_health_exempt(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200

    # ------------------------------------------------------------------
    # Login flow
    # ------------------------------------------------------------------

    def test_correct_pin_sets_session_and_redirects(self, client):
        csrf = _get_csrf(client)
        resp = client.post(
            "/login",
            data={"pin": self.PIN, "next": "/", "csrf_token": csrf},
        )
        assert resp.status_code == 302
        assert resp.headers["Location"] in ("/", "http://localhost/")
        # Session should be authed
        with client.session_transaction() as sess:
            assert sess.get("authed") is True

    def test_wrong_pin_renders_login_with_error(self, client):
        csrf = _get_csrf(client)
        resp = client.post(
            "/login",
            data={"pin": "wrong", "next": "/", "csrf_token": csrf},
        )
        assert resp.status_code == 200
        data = resp.get_data(as_text=True)
        assert "Incorrect PIN" in data

    def test_wrong_pin_does_not_set_authed(self, client):
        csrf = _get_csrf(client)
        client.post("/login", data={"pin": "wrong", "next": "/", "csrf_token": csrf})
        with client.session_transaction() as sess:
            assert sess.get("authed") is not True

    # ------------------------------------------------------------------
    # Rate-limit / lockout
    # ------------------------------------------------------------------

    def test_lockout_after_five_failures(self, client):
        for _ in range(5):
            csrf = _get_csrf(client)
            client.post("/login", data={"pin": "bad", "next": "/", "csrf_token": csrf})

        # 6th attempt — even with correct PIN — should be rejected
        csrf = _get_csrf(client)
        resp = client.post(
            "/login",
            data={"pin": self.PIN, "next": "/", "csrf_token": csrf},
        )
        assert resp.status_code == 200
        data = resp.get_data(as_text=True)
        assert "Too many failed attempts" in data
        with client.session_transaction() as sess:
            assert sess.get("authed") is not True

    def test_lockout_expires_after_60s(self, client, monkeypatch):
        """After lockout window elapses the user can log in again."""
        # Trigger lockout
        for _ in range(5):
            csrf = _get_csrf(client)
            client.post("/login", data={"pin": "bad", "next": "/", "csrf_token": csrf})

        # Fast-forward time past the lockout window
        future = time.time() + 61
        monkeypatch.setattr("blueprints.auth.time.time", lambda: future)

        csrf = _get_csrf(client)
        resp = client.post(
            "/login",
            data={"pin": self.PIN, "next": "/", "csrf_token": csrf},
        )
        assert resp.status_code == 302
        with client.session_transaction() as sess:
            assert sess.get("authed") is True

    # ------------------------------------------------------------------
    # Logout
    # ------------------------------------------------------------------

    def test_logout_clears_session(self, client):
        with client.session_transaction() as sess:
            sess["authed"] = True

        resp = client.get("/logout")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

        with client.session_transaction() as sess:
            assert sess.get("authed") is not True
