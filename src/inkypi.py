#!/usr/bin/env python3

import argparse
import logging
import os
import warnings
from time import perf_counter

from flask import Flask, g, url_for as flask_url_for
from jinja2 import ChoiceLoader, FileSystemLoader
from waitress import serve  # type: ignore
from werkzeug.serving import is_running_from_reloader

from app_setup.asset_helpers import setup_asset_helpers
from app_setup.blueprints_registry import register_blueprints

# Re-exports for backwards compatibility — some tests and external code
# import these symbols from `inkypi` directly. Kept here as module-level
# aliases after the JTN-289 split.
from app_setup.error_handlers import (
    register_error_handlers,
    register_error_handlers as _register_error_handlers,
)
from app_setup.health import (
    register_health_endpoints,
    register_health_endpoints as _register_health_endpoints,
)
from app_setup.http_metrics import setup_http_metrics
from app_setup.logging_setup import install_dev_log_handler, setup_logging
from app_setup.security_middleware import (
    _extract_csrf_token_from_request,
    _generate_csrf_token,
    setup_csrf_protection,
    setup_csrf_protection as _setup_csrf_protection,
    setup_https_redirect,
    setup_https_redirect as _setup_https_redirect,
    setup_rate_limiting,
    setup_rate_limiting as _setup_rate_limiting,
    setup_secret_key,
    setup_secret_key as _setup_secret_key,
    setup_security_headers,
    setup_security_headers as _setup_security_headers,
)
from app_setup.signals import (
    setup_signal_handlers,
    setup_signal_handlers as _setup_signal_handlers,
)
from config import Config
from display.display_manager import DisplayManager
from plugins.plugin_registry import load_plugins, pop_hot_reload_info
from refresh_task import RefreshTask
from utils.app_utils import generate_startup_image, get_ip_address
from utils.config_schema import ConfigValidationError

# Re-exported for tests/unit/test_inkypi.py monkey-patches.
__all__ = [
    "pop_hot_reload_info",
    "_register_error_handlers",
    "_register_health_endpoints",
    "_setup_csrf_protection",
    "_setup_https_redirect",
    "_setup_rate_limiting",
    "_setup_secret_key",
    "_setup_security_headers",
    "_setup_signal_handlers",
    "_extract_csrf_token_from_request",
    "_generate_csrf_token",
]

# suppress warning from inky library https://github.com/pimoroni/inky/issues/205
warnings.filterwarnings("ignore", message=".*Busy Wait: Held high.*")

# Register HEIF/HEIC image support (for iPhone photos)
try:
    from pi_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass  # pi-heif not installed, skip HEIF support


setup_logging()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level runtime config (env-derived; main() may overwrite)
# ---------------------------------------------------------------------------

_TRUTHY = frozenset({"1", "true", "yes"})
_DEFAULT_MAX_UPLOAD = 10 * 1024 * 1024


def _env_bool(name: str, default: str = "") -> bool:
    """Return True when the environment variable *name* holds a truthy value."""
    return os.getenv(name, default).strip().lower() in _TRUTHY


def _env_dev_mode() -> bool:
    env_mode = (
        os.getenv("INKYPI_ENV", "").strip() or os.getenv("FLASK_ENV", "").strip()
    ).lower()
    return env_mode in ("dev", "development")


DEV_MODE = _env_dev_mode()
WEB_ONLY = _env_bool("INKYPI_NO_REFRESH")
FAST_DEV = _env_bool("INKYPI_FAST_DEV")


def _env_port() -> int:
    env_port = os.getenv("INKYPI_PORT") or os.getenv("PORT")
    if env_port:
        try:
            return int(env_port)
        except ValueError:
            return 8080 if DEV_MODE else 80
    return 8080 if DEV_MODE else 80


PORT = _env_port()
args = None  # Populated by main()
app: Flask | None = None


def _resolve_port(cli_port, dev_mode):
    """Determine the port to listen on from CLI arg then env vars then default."""
    if cli_port is not None:
        return cli_port
    env_port = os.getenv("INKYPI_PORT") or os.getenv("PORT")
    if env_port:
        try:
            return int(env_port)
        except ValueError:
            pass
    return 8080 if dev_mode else 80


def _apply_dev_env(args):
    """Persist dev-mode flags to the environment for downstream consumers."""
    os.environ["INKYPI_ENV"] = "dev"
    if args.web_only:
        os.environ["INKYPI_NO_REFRESH"] = "1"


def _read_version() -> str:
    """Read the application version from the VERSION file at the repo root."""
    try:
        version_path = os.path.join(os.path.dirname(__file__), "..", "VERSION")
        with open(version_path) as f:
            return f.read().strip()
    except Exception:
        return "unknown"


def main(argv: list[str] | None = None):
    """Parse CLI arguments and initialise the application."""

    global args, DEV_MODE, WEB_ONLY, FAST_DEV, PORT, app

    parser = argparse.ArgumentParser(description="InkyPi Display Server")
    parser.add_argument("--dev", action="store_true", help="Run in development mode")
    parser.add_argument(
        "--config", type=str, default=None, help="Path to device config JSON file"
    )
    parser.add_argument("--port", type=int, default=None, help="Port to listen on")
    parser.add_argument(
        "--web-only",
        "--no-refresh",
        dest="web_only",
        action="store_true",
        help="Run web UI only (disable background refresh task)",
    )
    parser.add_argument(
        "--fast-dev",
        action="store_true",
        help="Use faster refresh intervals and skip startup image in dev",
    )
    args, _unknown = parser.parse_known_args(argv)

    # Infer DEV_MODE from CLI or environment
    env_mode = (
        os.getenv("INKYPI_ENV", "").strip() or os.getenv("FLASK_ENV", "").strip()
    ).lower()
    DEV_MODE = bool(args.dev or env_mode in ("dev", "development"))

    # Toggle for disabling background refresh thread
    WEB_ONLY = bool(args.web_only or _env_bool("INKYPI_NO_REFRESH"))

    if args.dev:
        _apply_dev_env(args)

    if args.config:
        Config.config_file = args.config

    PORT = _resolve_port(args.port, DEV_MODE)

    mode_label = "DEVELOPMENT" if DEV_MODE else "PRODUCTION"
    logger.info(f"Starting InkyPi in {mode_label} mode on port {PORT}")
    logging.getLogger("waitress.queue").setLevel(logging.ERROR)
    FAST_DEV = bool(args.fast_dev or _env_bool("INKYPI_FAST_DEV"))

    app = create_app()

    if DEV_MODE:
        install_dev_log_handler()

    return app


def create_app():
    """Build and configure the Flask application.

    Middleware, error handlers, health endpoints, and signal handling are
    delegated to focused modules under src/app_setup/ (see JTN-289).
    """
    app = Flask(__name__)
    template_dirs = [
        os.path.join(os.path.dirname(__file__), "templates"),
        os.path.join(os.path.dirname(__file__), "plugins"),
    ]
    app.jinja_loader = ChoiceLoader(
        [FileSystemLoader(directory) for directory in template_dirs]
    )

    app.config["APP_VERSION"] = _read_version()

    @app.context_processor
    def _inject_app_version():
        version = app.config["APP_VERSION"]

        def versioned_url_for(endpoint, **values):
            if endpoint == "static":
                values.setdefault("v", version)
            return flask_url_for(endpoint, **values)

        return {"app_version": version, "url_for": versioned_url_for}

    try:
        device_config = Config()
    except ConfigValidationError as exc:
        logger.error("Config invalid: %s", exc)
        raise SystemExit(1) from exc
    display_manager = DisplayManager(device_config)
    refresh_task = RefreshTask(device_config, display_manager)

    if FAST_DEV:
        try:
            device_config.update_value("plugin_cycle_interval_seconds", 30)
            device_config.update_value("startup", False)
            logger.info(
                "Fast dev mode enabled: plugin cycle set to 30s; startup image disabled"
            )
        except Exception:
            pass

    load_plugins(device_config.get_plugins())

    app.config["DEVICE_CONFIG"] = device_config
    app.config["DISPLAY_MANAGER"] = display_manager
    app.config["REFRESH_TASK"] = refresh_task
    app.config["WEB_ONLY"] = WEB_ONLY

    setup_secret_key(app, device_config)

    from app_setup.auth import init_auth

    init_auth(app, device_config)

    app.config["MAX_FORM_PARTS"] = 10_000
    try:
        _max_len_env = os.getenv("MAX_CONTENT_LENGTH") or os.getenv("MAX_UPLOAD_BYTES")
        _max_len = int(_max_len_env) if _max_len_env else _DEFAULT_MAX_UPLOAD
    except Exception:
        _max_len = _DEFAULT_MAX_UPLOAD
    app.config["MAX_CONTENT_LENGTH"] = _max_len

    register_blueprints(app)
    setup_asset_helpers(app)
    register_health_endpoints(app)

    @app.before_request
    def _ensure_refresh_task_started():
        if WEB_ONLY:
            return
        if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
            rt = app.config.get("REFRESH_TASK")
            if rt and not rt.running:
                logger.info("Starting refresh task (flask dev server lazy start)")
                rt.start()

    @app.before_request
    def _start_request_timer():
        try:
            g._t0 = perf_counter()
        except Exception:
            pass

    setup_https_redirect(app, dev_mode=DEV_MODE)

    @app.before_request
    def _attach_request_id():
        try:
            from utils.http_utils import _get_or_set_request_id

            _get_or_set_request_id()
        except Exception:
            pass

    setup_csrf_protection(app)
    setup_rate_limiting(app)
    register_error_handlers(app)
    setup_security_headers(app, dev_mode=DEV_MODE)
    setup_http_metrics(app)
    setup_signal_handlers(app)

    return app


if __name__ == "__main__":
    created_app = main()

    app = created_app

    refresh_task_obj = created_app.config.get("REFRESH_TASK")
    if not WEB_ONLY and not is_running_from_reloader() and refresh_task_obj is not None:
        refresh_task_obj.start()
    else:
        logger.info("Web-only mode enabled: background refresh task will not start")

    device_cfg = created_app.config.get("DEVICE_CONFIG")
    if (
        not WEB_ONLY
        and device_cfg is not None
        and device_cfg.get_config("startup") is True
    ):
        import threading

        def _show_startup():
            try:
                logger.info("Displaying startup image")
                img = generate_startup_image(device_cfg.get_resolution())
                display_manager_obj = created_app.config.get("DISPLAY_MANAGER")
                if display_manager_obj is not None:
                    display_manager_obj.display_image(img)
                device_cfg.update_value("startup", False, write=True)
            except Exception:
                logger.exception("Startup image failed")

        threading.Thread(target=_show_startup, daemon=True, name="StartupImage").start()

    try:
        from cysystemd.daemon import notify as sd_notify

        sd_notify("READY=1")
        logger.info("Notified systemd: READY=1")
    except Exception:
        pass

    try:
        if DEV_MODE:
            local_ip = get_ip_address()
            if local_ip:
                logger.info(f"Serving on http://{local_ip}:{PORT}")

        serve(created_app, host="0.0.0.0", port=PORT, threads=4)
    finally:
        refresh_task_obj = created_app.config.get("REFRESH_TASK")
        if refresh_task_obj is not None:
            refresh_task_obj.stop()
