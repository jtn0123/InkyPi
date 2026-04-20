# pyright: reportMissingImports=false
"""Auth-boundary coverage for privileged settings/device-admin flows.

This file stays intentionally read-mostly with respect to the existing route
tests: it uses the production app bootstrap and adds only auth-layer
assertions for sensitive routes. Route-specific validation/happy-path coverage
continues to live in the dedicated settings/update/system test modules.
"""

from __future__ import annotations

import importlib

import pytest

PIN = "2468"
READONLY_TOKEN = "jtn-760-readonly-token"

_PRIVILEGED_GET_CASES = (
    pytest.param("/settings", id="settings-page"),
    pytest.param("/settings/export", id="settings-export"),
    pytest.param("/settings/api-keys", id="api-keys-page"),
    pytest.param("/settings/update_status", id="update-status"),
)

_PRIVILEGED_POST_CASES = (
    pytest.param("/save_settings", {"data": {}}, id="save-settings"),
    pytest.param(
        "/settings/save_api_keys",
        {"data": {"NASA_SECRET": "should-not-reach-handler"}},
        id="save-api-keys",
    ),
    pytest.param(
        "/settings/delete_api_key",
        {"data": {"key": "NASA_SECRET"}},
        id="delete-api-key",
    ),
    pytest.param(
        "/settings/import",
        {"json": {"config": {"name": "unauthorized"}}},
        id="import-settings",
    ),
    pytest.param(
        "/settings/export", {"json": {"include_keys": True}}, id="export-post"
    ),
    pytest.param("/settings/safe_reset", {}, id="safe-reset"),
    pytest.param(
        "/settings/isolation",
        {"json": {"plugin_id": "clock"}},
        id="plugin-isolation",
    ),
    pytest.param("/settings/update", {}, id="start-update"),
    pytest.param("/settings/update/rollback", {}, id="start-rollback"),
    pytest.param("/shutdown", {"json": {}}, id="shutdown"),
)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _assert_redirects_to_login(resp) -> None:
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


@pytest.fixture()
def secured_app(device_config_dev, monkeypatch):
    """Build the real Flask app with PIN auth and read-only token enabled."""
    import inkypi
    from app_setup import security_middleware
    from display.display_manager import DisplayManager
    from plugins.plugin_registry import load_plugins
    from refresh_task import RefreshTask
    from utils.rate_limiter import SlidingWindowLimiter

    monkeypatch.setenv("INKYPI_AUTH_PIN", PIN)
    monkeypatch.setenv("INKYPI_READONLY_TOKEN", READONLY_TOKEN)
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-auth-boundaries")
    monkeypatch.setenv("INKYPI_RATE_LIMIT_AUTH", "100000/60")
    monkeypatch.setenv("INKYPI_RATE_LIMIT_REFRESH", "100000/60")
    monkeypatch.setenv("INKYPI_RATE_LIMIT_MUTATING", "100000/60")
    monkeypatch.delenv("INKYPI_ENV", raising=False)
    monkeypatch.delenv("FLASK_ENV", raising=False)

    inkypi = importlib.reload(inkypi)
    security_middleware._mutation_limiter = SlidingWindowLimiter(100000, 60)

    def _fake_init_core_services(app):
        display_manager = DisplayManager(device_config_dev)
        refresh_task = RefreshTask(device_config_dev, display_manager)
        load_plugins(device_config_dev.get_plugins())
        app.config["DEVICE_CONFIG"] = device_config_dev
        app.config["DISPLAY_MANAGER"] = display_manager
        app.config["REFRESH_TASK"] = refresh_task
        app.config["WEB_ONLY"] = False
        return device_config_dev

    def _setup_csrf_token_only(app):
        import secrets as _secrets

        from flask import session as _session

        def _generate_csrf_token() -> str:
            if "_csrf_token" not in _session:
                _session["_csrf_token"] = _secrets.token_hex(32)
            return _session["_csrf_token"]

        @app.context_processor
        def _inject_csrf_token():
            return {"csrf_token": _generate_csrf_token}

    monkeypatch.setattr(inkypi, "_init_core_services", _fake_init_core_services)
    monkeypatch.setattr(inkypi, "setup_csrf_protection", _setup_csrf_token_only)
    monkeypatch.setattr(inkypi, "setup_signal_handlers", lambda app: None)

    return inkypi.create_app()


@pytest.fixture()
def secured_client(secured_app):
    return secured_app.test_client()


class TestPrivilegedRoutesRequirePinSession:
    @pytest.mark.parametrize("path", _PRIVILEGED_GET_CASES)
    def test_unauthenticated_get_redirects_to_login(self, secured_client, path):
        resp = secured_client.get(path, follow_redirects=False)
        _assert_redirects_to_login(resp)

    @pytest.mark.parametrize(("path", "request_kwargs"), _PRIVILEGED_POST_CASES)
    def test_unauthenticated_post_redirects_to_login(
        self, secured_client, path, request_kwargs
    ):
        resp = secured_client.post(path, follow_redirects=False, **request_kwargs)
        _assert_redirects_to_login(resp)


class TestReadonlyTokenCannotBypassPrivilegedRoutes:
    def test_readonly_token_sanity_check_still_allows_monitoring_route(
        self, secured_client
    ):
        resp = secured_client.get(
            "/api/version/info",
            headers=_bearer(READONLY_TOKEN),
            follow_redirects=False,
        )
        assert resp.status_code == 200

    @pytest.mark.parametrize("path", _PRIVILEGED_GET_CASES)
    def test_readonly_token_get_still_redirects_on_privileged_route(
        self, secured_client, path
    ):
        resp = secured_client.get(
            path,
            headers=_bearer(READONLY_TOKEN),
            follow_redirects=False,
        )
        _assert_redirects_to_login(resp)

    @pytest.mark.parametrize(("path", "request_kwargs"), _PRIVILEGED_POST_CASES)
    def test_readonly_token_post_still_redirects_on_privileged_route(
        self, secured_client, path, request_kwargs
    ):
        resp = secured_client.post(
            path,
            headers=_bearer(READONLY_TOKEN),
            follow_redirects=False,
            **request_kwargs,
        )
        _assert_redirects_to_login(resp)
