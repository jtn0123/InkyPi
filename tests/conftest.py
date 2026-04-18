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
    "test_plugin_draft_add_to_playlist.py",
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
    "test_click_sweep.py",
    "test_jtn_681_clock_face_picker.py",
    "test_toggle_reflection.py",
    "test_layout_overlap.py",
    "test_plugin_preview_smoke.py",
    "test_plugin_preview_save_roundtrip.py",
    "test_form_roundtrip.py",
    "test_playlist_roundtrip.py",
    "test_playlist_roundtrip_mobile.py",
    "test_api_key_roundtrip.py",
    "test_jtn_720_721_722_journeys.py",
    # JTN-724 update-flow happy-path journey.
    "test_update_flow_happy_path.py",
    # JTN-719 device-actions journey (reboot/shutdown confirm/cancel flow).
    "test_device_actions_roundtrip.py",
    # JTN-728/727/726/725 device/update/ops journey bundle.
    "test_device_update_ops_journeys.py",
    # JTN-727 logs-access journey (trigger error, download, verify payload).
    "test_logs_access.py",
    # JTN-726 refresh-interval change journey (UI save -> reload -> diagnostics).
    "test_refresh_interval_change.py",
}
A11Y_BROWSER_TESTS = {
    "test_a11y_sweep.py",
    "test_axe_a11y.py",
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
    "GOOGLE_AI_SECRET",
)


def pytest_addoption(parser):
    parser.addoption(
        "--update-snapshots",
        action="store_true",
        default=False,
        help="Regenerate tests/snapshots baselines instead of asserting diffs.",
    )


def pytest_configure(config):
    if config.getoption("--update-snapshots"):
        os.environ["SNAPSHOT_UPDATE"] = "1"


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
def reset_plugin_registry_state():
    """Prevent plugin registry globals from leaking between tests."""
    from plugins.plugin_registry import reset_plugin_registry

    reset_plugin_registry()
    yield
    reset_plugin_registry()


@pytest.fixture(autouse=True)
def mock_screenshot(monkeypatch):
    # Return a simple in-memory image instead of invoking chromium
    def _fake_screenshot(*args, **kwargs):
        dims = args[1] if len(args) > 1 else kwargs.get("dimensions", (800, 480))
        width, height = dims
        return Image.new("RGB", (width, height), "white")

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
def reset_utils_singletons():
    """Reset utils module-level singletons before each test.

    Prevents HTTP session state, cache contents, and i18n locale state from
    leaking across tests regardless of execution order.
    """
    from utils.http_cache import reset_for_tests as _reset_http_cache
    from utils.http_client import reset_for_tests as _reset_http_session
    from utils.i18n import reset_for_tests as _reset_i18n

    _reset_http_session()
    _reset_http_cache()
    _reset_i18n()
    yield
    _reset_http_session()
    _reset_http_cache()
    _reset_i18n()


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
    # Build the app through the production bootstrap path so tests exercise the
    # same middleware registration that ships in inkypi.py.
    import secrets as _secrets

    from flask import session as _session

    import inkypi
    from display.display_manager import DisplayManager
    from plugins.plugin_registry import load_plugins
    from refresh_task import RefreshTask

    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-csrf")

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
