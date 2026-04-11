# pyright: reportMissingImports=false
"""Tests for the JTN-613 smoke render endpoint.

The ``/__smoke/render`` route is an opt-in helper consumed by
``scripts/test_install_memcap.sh`` Phase 4 to exercise the plugin render path
in a live container so the peak RSS sample actually reflects a real
``generate_image()`` call. It must be:

* Absent from the app when ``INKYPI_SMOKE_FORCE_RENDER`` is unset (production)
* Present and CSRF-exempt when the env var is set
* Responsive to a POST that names a real plugin (clock), returning 200 and
  image dimensions
"""

from __future__ import annotations

import pytest
from flask import Flask

from app_setup.smoke import (
    SMOKE_RENDER_ENV_VAR,
    SMOKE_RENDER_PATH,
    register_smoke_endpoints,
    smoke_render_enabled,
)


class _StubImage:
    """Minimal PIL-ish stub so the endpoint can report width/height."""

    def __init__(self, width: int = 800, height: int = 480) -> None:
        self.width = width
        self.height = height


class _StubPlugin:
    def __init__(self, image: _StubImage | None = None) -> None:
        self._image = image or _StubImage()
        self.calls = 0

    def generate_image(self, settings, device_config):  # pragma: no cover - trivial
        self.calls += 1
        return self._image


class _StubDeviceConfig:
    def __init__(self, plugins: dict) -> None:
        self._plugins = plugins

    def get_plugin(self, plugin_id):
        return self._plugins.get(plugin_id)


def _make_app(
    *,
    device_config: _StubDeviceConfig | None = None,
    stub_plugin: _StubPlugin | None = None,
) -> Flask:
    """Build a tiny Flask app wired just enough for the smoke endpoint."""
    app = Flask(__name__)
    app.secret_key = "test-smoke-render"
    if device_config is not None:
        app.config["DEVICE_CONFIG"] = device_config
    register_smoke_endpoints(app)
    # Patch the lazily-imported plugin registry so we don't actually load plugins.
    if stub_plugin is not None:
        import plugins.plugin_registry as registry

        app._orig_get_plugin_instance = registry.get_plugin_instance  # type: ignore[attr-defined]
        registry.get_plugin_instance = lambda plugin_config: stub_plugin  # type: ignore[assignment]
    return app


@pytest.fixture(autouse=True)
def _restore_registry(request):
    """Restore plugins.plugin_registry.get_plugin_instance after each test."""
    yield
    try:
        import plugins.plugin_registry as registry

        for app in getattr(request.node, "_smoke_apps", []) or []:
            orig = getattr(app, "_orig_get_plugin_instance", None)
            if orig is not None:
                registry.get_plugin_instance = orig
    except Exception:
        pass


def test_smoke_render_not_registered_without_env_var(monkeypatch):
    monkeypatch.delenv(SMOKE_RENDER_ENV_VAR, raising=False)
    assert smoke_render_enabled() is False

    app = _make_app()
    client = app.test_client()

    # Route should not exist — Flask returns 404 for unregistered paths.
    resp = client.post(SMOKE_RENDER_PATH, data={"plugin_id": "clock"})
    assert resp.status_code == 404

    # And it must not appear in the URL map at all.
    rules = [str(rule) for rule in app.url_map.iter_rules()]
    assert SMOKE_RENDER_PATH not in rules


@pytest.mark.parametrize("value", ["1", "true", "yes", "TRUE", "Yes"])
def test_smoke_render_enabled_truthy_values(monkeypatch, value):
    monkeypatch.setenv(SMOKE_RENDER_ENV_VAR, value)
    assert smoke_render_enabled() is True


@pytest.mark.parametrize("value", ["", "0", "no", "false", "off", "maybe"])
def test_smoke_render_disabled_falsy_values(monkeypatch, value):
    monkeypatch.setenv(SMOKE_RENDER_ENV_VAR, value)
    assert smoke_render_enabled() is False


def test_smoke_render_registered_when_env_var_set(monkeypatch):
    monkeypatch.setenv(SMOKE_RENDER_ENV_VAR, "1")
    stub_plugin = _StubPlugin(_StubImage(width=800, height=480))
    device_config = _StubDeviceConfig({"clock": {"plugin_id": "clock"}})
    app = _make_app(device_config=device_config, stub_plugin=stub_plugin)

    rules = [str(rule) for rule in app.url_map.iter_rules()]
    assert SMOKE_RENDER_PATH in rules


def test_smoke_render_calls_generate_image(monkeypatch):
    monkeypatch.setenv(SMOKE_RENDER_ENV_VAR, "1")
    stub_plugin = _StubPlugin(_StubImage(width=800, height=480))
    device_config = _StubDeviceConfig({"clock": {"plugin_id": "clock"}})
    app = _make_app(device_config=device_config, stub_plugin=stub_plugin)
    client = app.test_client()

    resp = client.post(SMOKE_RENDER_PATH, data={"plugin_id": "clock"})
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload == {
        "ok": True,
        "plugin_id": "clock",
        "width": 800,
        "height": 480,
    }
    assert stub_plugin.calls == 1

    # And a second POST increments the counter — the smoke script hits the
    # endpoint multiple times to build up sustained working set.
    resp = client.post(SMOKE_RENDER_PATH, data={"plugin_id": "clock"})
    assert resp.status_code == 200
    assert stub_plugin.calls == 2


def test_smoke_render_missing_plugin_id_returns_422(monkeypatch):
    monkeypatch.setenv(SMOKE_RENDER_ENV_VAR, "1")
    device_config = _StubDeviceConfig({})
    app = _make_app(device_config=device_config, stub_plugin=_StubPlugin())
    client = app.test_client()

    resp = client.post(SMOKE_RENDER_PATH, data={})
    assert resp.status_code == 422


def test_smoke_render_unknown_plugin_returns_404(monkeypatch):
    monkeypatch.setenv(SMOKE_RENDER_ENV_VAR, "1")
    device_config = _StubDeviceConfig({})  # no plugins at all
    app = _make_app(device_config=device_config, stub_plugin=_StubPlugin())
    client = app.test_client()

    resp = client.post(SMOKE_RENDER_PATH, data={"plugin_id": "missing"})
    assert resp.status_code == 404


def test_smoke_render_generate_image_exception_returns_500(monkeypatch):
    monkeypatch.setenv(SMOKE_RENDER_ENV_VAR, "1")

    class _Boom(_StubPlugin):
        def generate_image(self, settings, device_config):
            raise RuntimeError("boom")

    device_config = _StubDeviceConfig({"clock": {"plugin_id": "clock"}})
    app = _make_app(device_config=device_config, stub_plugin=_Boom())
    client = app.test_client()

    resp = client.post(SMOKE_RENDER_PATH, data={"plugin_id": "clock"})
    assert resp.status_code == 500


def test_smoke_render_does_not_touch_display_manager(monkeypatch):
    """The endpoint must NOT push to the display — that's not what we measure."""
    monkeypatch.setenv(SMOKE_RENDER_ENV_VAR, "1")

    class _TrackingDisplay:
        def __init__(self):
            self.calls = 0

        def display_image(self, *args, **kwargs):
            self.calls += 1

    stub_plugin = _StubPlugin()
    device_config = _StubDeviceConfig({"clock": {"plugin_id": "clock"}})
    app = _make_app(device_config=device_config, stub_plugin=stub_plugin)
    tracking_display = _TrackingDisplay()
    app.config["DISPLAY_MANAGER"] = tracking_display

    client = app.test_client()
    resp = client.post(SMOKE_RENDER_PATH, data={"plugin_id": "clock"})
    assert resp.status_code == 200
    assert (
        tracking_display.calls == 0
    ), "smoke render endpoint must not push to the display manager"


def test_smoke_render_csrf_exempt_in_security_middleware(monkeypatch):
    """JTN-613: the CSRF middleware must let /__smoke/render through when enabled.

    This is a behavioural guard: if a future refactor drops the
    SMOKE_RENDER_PATH check in setup_csrf_protection, the smoke test harness
    will silently go back to being CSRF-blocked and the peak RSS sample will
    revert to ~= idle. Fail loudly here instead.
    """
    monkeypatch.setenv(SMOKE_RENDER_ENV_VAR, "1")
    from app_setup.security_middleware import setup_csrf_protection

    stub_plugin = _StubPlugin()
    device_config = _StubDeviceConfig({"clock": {"plugin_id": "clock"}})
    app = _make_app(device_config=device_config, stub_plugin=stub_plugin)
    setup_csrf_protection(app)

    client = app.test_client()
    # No CSRF token in the POST body — should still be allowed because the
    # path is env-gated as exempt.
    resp = client.post(SMOKE_RENDER_PATH, data={"plugin_id": "clock"})
    assert resp.status_code == 200, (
        f"smoke render must be CSRF-exempt when INKYPI_SMOKE_FORCE_RENDER=1; "
        f"got {resp.status_code}"
    )


def test_smoke_render_csrf_still_enforced_for_other_paths(monkeypatch):
    """Sanity: enabling the smoke env var must not open up CSRF globally."""
    monkeypatch.setenv(SMOKE_RENDER_ENV_VAR, "1")
    from app_setup.security_middleware import setup_csrf_protection

    app = _make_app()
    setup_csrf_protection(app)

    @app.route("/other_mutation", methods=["POST"])
    def _other():
        return "ok", 200

    client = app.test_client()
    resp = client.post("/other_mutation", data={})
    assert resp.status_code == 403, (
        "CSRF must still be enforced for non-smoke paths even when "
        "INKYPI_SMOKE_FORCE_RENDER=1"
    )
