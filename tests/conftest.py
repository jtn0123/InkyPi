# pyright: reportMissingImports=false
import json
import os
import sys
import threading
from functools import lru_cache
from pathlib import Path

import pytest
from PIL import Image
from werkzeug.serving import make_server

# Ensure both project root (for `src.*` imports) and src/ (for top-level `utils`, `display`) are on sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
SRC_ABS = os.path.abspath(os.path.join(PROJECT_ROOT, "src"))
if SRC_ABS not in sys.path:
    sys.path.insert(0, SRC_ABS)

UI_BROWSER_TESTS = {
    "test_browser_smoke.py",
    "test_e2e_form_workflows.py",
    "test_playlist_interactions.py",
    "test_plugin_add_to_playlist_ui.py",
    "test_weather_autofill.py",
    "test_weather_image_render.py",
    "test_playlist_crud_e2e.py",
    "test_settings_round_trip_e2e.py",
    "test_plugin_workflow_e2e.py",
    "test_dashboard_display_next_e2e.py",
    "test_api_keys_e2e.py",
    "test_modal_lifecycle_e2e.py",
    "test_theme_toggle_e2e.py",
    "test_collapsible_sections_e2e.py",
    "test_cross_page_navigation_e2e.py",
}
A11Y_BROWSER_TESTS = {
    "test_more_a11y.py",
    "test_playlist_a11y.py",
}
MANAGED_API_KEY_ENV_VARS = (
    "OPEN_AI_SECRET",
    "OPEN_WEATHER_MAP_SECRET",
    "NASA_SECRET",
    "UNSPLASH_ACCESS_KEY",
    "IMMICH_KEY",
    "GITHUB_SECRET",
)


def _is_truthy(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes")


def _browser_test_group(path: Path) -> str | None:
    name = path.name
    if name in A11Y_BROWSER_TESTS:
        return "a11y"
    if name in UI_BROWSER_TESTS:
        return "ui"
    return None


@lru_cache(maxsize=1)
def _playwright_browser_available() -> bool:
    try:  # pragma: no cover - best effort detection
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            browser.close()
        return True
    except Exception:
        return False


def pytest_ignore_collect(collection_path, config):
    path = Path(str(collection_path))
    group = _browser_test_group(path)
    if group is None:
        return False

    # SKIP_BROWSER=1 skips all browser-dependent tests (a11y + UI).
    # SKIP_A11Y=1 / SKIP_UI=1 skip their respective groups independently.
    skip_browser = _is_truthy(os.getenv("SKIP_BROWSER", ""))
    skip_a11y = skip_browser or _is_truthy(os.getenv("SKIP_A11Y", ""))
    skip_ui = skip_browser or _is_truthy(os.getenv("SKIP_UI", ""))
    require_browser_smoke = _is_truthy(os.getenv("REQUIRE_BROWSER_SMOKE", ""))

    if skip_a11y and group == "a11y":
        return True
    if skip_ui and group == "ui" and not require_browser_smoke:
        return True
    if _playwright_browser_available():
        return False
    if require_browser_smoke and path.name == "test_browser_smoke.py":
        raise RuntimeError(
            "REQUIRE_BROWSER_SMOKE=1 but Playwright Chromium is unavailable. "
            "Install browsers with `playwright install chromium`."
        )
    return True


@pytest.fixture(autouse=True)
def disable_plugin_process_isolation(monkeypatch):
    """Run plugins in-process during tests.

    The production code spawns a subprocess per plugin execution to isolate
    failures.  On Linux the ``spawn``/``forkserver`` multiprocessing start
    methods require all arguments to be picklable and do **not** inherit
    monkey-patches from the test process.  Setting this env var tells
    ``RefreshTask._execute_with_policy`` to skip the subprocess and call the
    plugin directly, which is both faster and compatible with monkeypatch.
    """
    monkeypatch.setenv("INKYPI_PLUGIN_ISOLATION", "none")


@pytest.fixture(autouse=True)
def clear_managed_api_key_env(monkeypatch):
    # Keep tests hermetic even when earlier tests or the parent shell export real
    # API credentials that would otherwise leak into "missing key" cases.
    for env_var in MANAGED_API_KEY_ENV_VARS:
        monkeypatch.delenv(env_var, raising=False)

    try:
        import blueprints.playlist as playlist_mod
        import blueprints.settings as settings_mod

        playlist_mod._eta_cache.clear()
        settings_mod._logs_limiter._requests.clear()
        # Reset the shutdown rate limiter so tests are independent
        settings_mod._shutdown_limiter.reset()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def mock_screenshot(monkeypatch):
    # Return a simple in-memory image instead of invoking chromium
    def _fake_screenshot(*args, **kwargs):
        dims = args[1] if len(args) > 1 else kwargs.get("dimensions", (800, 480))
        width, height = dims
        img = Image.new("RGB", (width, height), "white")
        return img

    import plugins.base_plugin.base_plugin as base_plugin
    import utils.image_utils as image_utils

    monkeypatch.setattr(image_utils, "take_screenshot", _fake_screenshot, raising=True)
    monkeypatch.setattr(
        image_utils,
        "take_screenshot_html",
        lambda html, dimensions, timeout_ms=None: _fake_screenshot(None, dimensions),
        raising=True,
    )
    monkeypatch.setattr(
        base_plugin,
        "take_screenshot_html",
        lambda html, dimensions, timeout_ms=None: _fake_screenshot(None, dimensions),
        raising=True,
    )


# (Removed) Autouse requests.get stub to avoid interfering with tests that patch requests explicitly.


@pytest.fixture(autouse=True)
def reset_display_next_cooldown():
    """Reset the /display-next rate limiter between tests."""
    from blueprints.main import _reset_display_next_cooldown

    _reset_display_next_cooldown()
    yield
    _reset_display_next_cooldown()


@pytest.fixture()
def device_config_dev(tmp_path, monkeypatch):
    # Create a temp device config mirroring device_dev.json
    cfg = {
        "name": "InkyPi Test",
        "display_type": "mock",
        "resolution": [800, 480],
        "orientation": "horizontal",
        "output_dir": str(tmp_path / "mock_output"),
        "timezone": "UTC",
        "time_format": "24h",
        "plugin_cycle_interval_seconds": 300,
        "image_settings": {
            "saturation": 1.0,
            "brightness": 1.0,
            "sharpness": 1.0,
            "contrast": 1.0,
        },
        "playlist_config": {"playlists": [], "active_playlist": ""},
        "refresh_info": {
            "refresh_time": None,
            "image_hash": None,
            "refresh_type": "Manual Update",
            "plugin_id": "",
        },
    }
    config_file = tmp_path / "device.json"
    config_file.write_text(json.dumps(cfg))
    (tmp_path / ".env").write_text("", encoding="utf-8")

    # Ensure the app reads .env from the temp directory to avoid leaking real secrets
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))

    # Patch Config paths to use tmp dir
    import config as config_mod

    monkeypatch.setattr(config_mod.Config, "config_file", str(config_file))
    monkeypatch.setattr(
        config_mod.Config, "current_image_file", str(tmp_path / "current_image.png")
    )
    monkeypatch.setattr(
        config_mod.Config, "processed_image_file", str(tmp_path / "processed_image.png")
    )
    monkeypatch.setattr(
        config_mod.Config, "plugin_image_dir", str(tmp_path / "plugins")
    )
    monkeypatch.setattr(
        config_mod.Config, "history_image_dir", str(tmp_path / "history")
    )

    # Ensure plugin image dir exists
    os.makedirs(str(tmp_path / "plugins"), exist_ok=True)
    os.makedirs(str(tmp_path / "history"), exist_ok=True)

    return config_mod.Config()


@pytest.fixture()
def flask_app(device_config_dev, monkeypatch):
    # Build a Flask app instance similar to inkypi.py but without CLI parsing/threads
    import os
    import secrets as _secrets

    from flask import Flask, session as _session
    from jinja2 import ChoiceLoader, FileSystemLoader

    from blueprints.apikeys import apikeys_bp
    from blueprints.history import history_bp
    from blueprints.main import main_bp
    from blueprints.playlist import playlist_bp
    from blueprints.plugin import plugin_bp
    from blueprints.settings import settings_bp
    from display.display_manager import DisplayManager
    from plugins.plugin_registry import load_plugins
    from refresh_task import RefreshTask

    app = Flask(__name__)
    app.secret_key = "test-secret-key-for-csrf"

    # Template directories
    SRC_ABS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
    template_dirs = [
        os.path.join(SRC_ABS, "templates"),
        os.path.join(SRC_ABS, "plugins"),
    ]
    app.jinja_loader = ChoiceLoader(
        [FileSystemLoader(directory) for directory in template_dirs]
    )

    # Core services
    display_manager = DisplayManager(device_config_dev)
    refresh_task = RefreshTask(device_config_dev, display_manager)

    # Load plugins
    load_plugins(device_config_dev.get_plugins())

    # Store dependencies
    app.config["DEVICE_CONFIG"] = device_config_dev
    app.config["DISPLAY_MANAGER"] = display_manager
    app.config["REFRESH_TASK"] = refresh_task
    app.config["WEB_ONLY"] = False
    app.config["MAX_FORM_PARTS"] = 10_000
    # Mirror request size limit from app
    try:
        _max_len_env = os.getenv("MAX_CONTENT_LENGTH") or os.getenv("MAX_UPLOAD_BYTES")
        _max_len = int(_max_len_env) if _max_len_env else 10 * 1024 * 1024
    except Exception:
        _max_len = 10 * 1024 * 1024
    app.config["MAX_CONTENT_LENGTH"] = _max_len

    # CSRF token support (mirrors inkypi.py create_app)
    def _generate_csrf_token() -> str:
        if "_csrf_token" not in _session:
            _session["_csrf_token"] = _secrets.token_hex(32)
        return _session["_csrf_token"]

    @app.context_processor
    def _inject_csrf_token():
        return {"csrf_token": _generate_csrf_token}

    # Register routes
    app.register_blueprint(main_bp)
    app.register_blueprint(apikeys_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(plugin_bp)
    app.register_blueprint(playlist_bp)
    app.register_blueprint(history_bp)

    # Lightweight health endpoints for probes/CI
    @app.route("/healthz")
    def healthz():
        return ("OK", 200)

    @app.route("/readyz")
    def readyz():
        try:
            rt = app.config.get("REFRESH_TASK")
            web_only = bool(app.config.get("WEB_ONLY"))
            if web_only:
                return ("ready:web-only", 200)
            if rt and getattr(rt, "running", False):
                return ("ready", 200)
            return ("not-ready", 503)
        except Exception:
            return ("not-ready", 503)

    @app.errorhandler(404)
    def _handle_not_found(err):
        from utils.http_utils import json_error, wants_json

        if wants_json():
            return json_error("Not found", status=404)
        from flask import render_template as _rt

        return _rt("404.html"), 404

    @app.after_request
    def _set_security_headers(response):
        # Basic hardening headers
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        # Enable HSTS only when under HTTPS/behind a proxy forwarding HTTPS
        try:
            from flask import request

            if (
                request.is_secure
                or request.headers.get("X-Forwarded-Proto", "").lower() == "https"
            ):
                response.headers.setdefault(
                    "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
                )
        except Exception:
            pass
        # Content Security Policy (Report-Only by default)
        try:
            csp_value = (
                os.getenv("INKYPI_CSP")
                or "default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; script-src 'self'; font-src 'self' data:"
            )
            report_only = os.getenv("INKYPI_CSP_REPORT_ONLY", "1").strip().lower() in (
                "1",
                "true",
                "yes",
            )
            header_name = (
                "Content-Security-Policy-Report-Only"
                if report_only
                else "Content-Security-Policy"
            )
            if header_name not in response.headers:
                response.headers[header_name] = csp_value
        except Exception:
            pass
        return response

    return app


@pytest.fixture()
def client(flask_app):
    return flask_app.test_client()


@pytest.fixture()
def live_server(
    flask_app, free_tcp_port_factory
):  # free_tcp_port_factory: from anyio pytest plugin
    host = "127.0.0.1"
    port = free_tcp_port_factory()
    server = make_server(host, port, flask_app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
