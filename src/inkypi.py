#!/usr/bin/env python3

import argparse
import logging
import logging.config
import os
import secrets
import signal
import warnings
from collections import defaultdict, deque
from time import perf_counter

from flask import (
    Flask,
    g,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for as flask_url_for,
)
from jinja2 import ChoiceLoader, FileSystemLoader
from waitress import serve  # type: ignore
from werkzeug.serving import is_running_from_reloader

from config import Config
from display.display_manager import DisplayManager
from plugins.plugin_registry import load_plugins, pop_hot_reload_info
from refresh_task import RefreshTask
from utils.app_utils import generate_startup_image, get_ip_address
from utils.http_utils import APIError, json_error, json_internal_error, wants_json

# suppress warning from inky library https://github.com/pimoroni/inky/issues/205
warnings.filterwarnings("ignore", message=".*Busy Wait: Held high.*")

# Register HEIF/HEIC image support (for iPhone photos)
try:
    from pi_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass  # pi-heif not installed, skip HEIF support


def _use_json_logging():
    fmt = (os.getenv("INKYPI_LOG_FORMAT") or "").strip().lower()
    return fmt == "json"


def _setup_logging():
    if _use_json_logging():
        logging.config.dictConfig(
            {
                "version": 1,
                "disable_existing_loggers": False,
                "formatters": {
                    "json": {
                        "()": "utils.logging_utils.JsonFormatter",
                    }
                },
                "handlers": {
                    "console": {
                        "class": "logging.StreamHandler",
                        "level": os.getenv("INKYPI_LOG_LEVEL", "INFO").upper(),
                        "formatter": "json",
                        "stream": "ext://sys.stdout",
                    }
                },
                "root": {
                    "level": os.getenv("INKYPI_LOG_LEVEL", "INFO").upper(),
                    "handlers": ["console"],
                },
            }
        )
    else:
        logging.config.fileConfig(
            os.path.join(os.path.dirname(__file__), "config", "logging.conf"),
            disable_existing_loggers=False,
        )


_setup_logging()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_TRUTHY = frozenset({"1", "true", "yes"})

# Named constants (formerly magic numbers)
_CACHE_1_YEAR = 31_536_000
_CACHE_1_DAY = 86_400
_DEFAULT_MAX_UPLOAD = 10 * 1024 * 1024


def _env_bool(name: str, default: str = "") -> bool:
    """Return True when the environment variable *name* holds a truthy value."""
    return os.getenv(name, default).strip().lower() in _TRUTHY


"""Runtime configuration.

When imported, values are derived from environment variables only. The
``main`` function performs CLI parsing and updates these globals when invoked.
"""


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
# Flask app is created in main()/create_app(); declare as Optional for runtime init,
# but we will guard all uses below so mypy understands non-None when accessed.
app: Flask | None = None


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

    # If --dev explicitly passed, set env var for downstream logic and logs
    if args.dev:
        os.environ["INKYPI_ENV"] = "dev"
        # If explicitly opting for web-only via CLI, mirror it in the environment for downstream logic
        if args.web_only:
            os.environ["INKYPI_NO_REFRESH"] = "1"

    # Config file selection via CLI has highest priority; otherwise resolver will decide
    if args.config:
        Config.config_file = args.config

    # Determine port
    if args.port is not None:
        PORT = args.port
    else:
        # Prefer env INKYPI_PORT then PORT; default by mode
        env_port = os.getenv("INKYPI_PORT") or os.getenv("PORT")
        if env_port:
            try:
                PORT = int(env_port)
            except ValueError:
                PORT = 8080 if DEV_MODE else 80
        else:
            PORT = 8080 if DEV_MODE else 80

    if DEV_MODE:
        logger.info(f"Starting InkyPi in DEVELOPMENT mode on port {PORT}")
    else:
        logger.info(f"Starting InkyPi in PRODUCTION mode on port {PORT}")
    logging.getLogger("waitress.queue").setLevel(logging.ERROR)
    FAST_DEV = bool(args.fast_dev or _env_bool("INKYPI_FAST_DEV"))

    app = create_app()

    # Enable dev mode logging handler for in-memory log capture
    if DEV_MODE:
        try:
            from blueprints.settings import DevModeLogHandler

            dev_handler = DevModeLogHandler()
            dev_handler.setLevel(logging.DEBUG)
            logging.getLogger().addHandler(dev_handler)
            logger.info("Dev mode log handler enabled (in-memory buffer)")
        except Exception as e:
            logger.warning(f"Could not enable dev mode log handler: {e}")

    return app


def _read_version() -> str:
    """Read the application version from the VERSION file at the repo root."""
    try:
        version_path = os.path.join(os.path.dirname(__file__), "..", "VERSION")
        with open(version_path) as f:
            return f.read().strip()
    except Exception:
        return "unknown"


def _register_error_handlers(app: Flask) -> None:
    """Register JSON-aware error handlers for common HTTP status codes."""

    @app.errorhandler(APIError)
    def _handle_api_error(err: APIError):
        return json_error(
            err.message, status=err.status, code=err.code, details=err.details
        )

    @app.errorhandler(400)
    def _handle_bad_request(err):
        if wants_json():
            return json_error("Bad request", status=400)
        return make_response("Bad request", 400)

    @app.errorhandler(404)
    def _handle_not_found(err):
        if wants_json():
            return json_error("Not found", status=404)
        return render_template("404.html"), 404

    @app.errorhandler(415)
    def _handle_unsupported_media_type(err):
        if wants_json():
            return json_error("Unsupported media type", status=415)
        return make_response("Unsupported media type", 415)

    @app.errorhandler(Exception)
    def _handle_unexpected_error(err: Exception):
        try:
            logger.exception("Unhandled exception: %s", err)
        except Exception:
            pass
        if wants_json():
            return json_internal_error(
                "unhandled application error",
                details={
                    "hint": "Check server logs for stack trace; enable DEV mode for more diagnostics.",
                },
            )
        return make_response("Internal Server Error", 500)


# ---------------------------------------------------------------------------
# create_app helpers — extracted for cognitive-complexity (SonarCloud S3776)
# ---------------------------------------------------------------------------

_CSRF_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_CSRF_EXEMPT_PATHS = frozenset({"/healthz", "/readyz"})
_MUTATE_WINDOW = 60  # seconds
_MUTATE_MAX = 60  # requests per IP per window
_RATE_EXEMPT = frozenset({"/healthz", "/readyz"})


def _setup_secret_key(app: Flask, device_config: Config) -> None:
    secret = os.getenv("SECRET_KEY")
    if not secret:
        try:
            secret = device_config.load_env_key("SECRET_KEY")
        except Exception:
            secret = None
    if not secret:
        generated = secrets.token_hex(32)
        try:
            device_config.set_env_key("SECRET_KEY", generated)
            secret = generated
            logger.info("SECRET_KEY not set; generated and persisted to .env")
        except Exception as e:
            secret = generated
            logger.warning(
                "SECRET_KEY could not persist: %s — sessions won't survive restarts", e
            )
    app.secret_key = secret
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


def _register_blueprints(app: Flask) -> None:
    from blueprints.apikeys import apikeys_bp
    from blueprints.history import history_bp
    from blueprints.main import main_bp
    from blueprints.playlist import playlist_bp
    from blueprints.plugin import plugin_bp
    from blueprints.settings import settings_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(apikeys_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(plugin_bp)
    app.register_blueprint(playlist_bp)
    app.register_blueprint(history_bp)


def _register_health_endpoints(app: Flask) -> None:
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


def _setup_https_redirect(app: Flask) -> None:
    force_https = not DEV_MODE and _env_bool("INKYPI_FORCE_HTTPS")

    @app.before_request
    def _redirect_to_https():
        if not force_https:
            return
        if (
            request.is_secure
            or request.headers.get("X-Forwarded-Proto", "").lower() == "https"
        ):
            return
        url = request.url.replace("http://", "https://", 1)
        return redirect(url, code=301)


def _generate_csrf_token() -> str:
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_hex(32)
    return session["_csrf_token"]


def _setup_csrf_protection(app: Flask) -> None:
    @app.context_processor
    def _inject_csrf_token():
        return {"csrf_token": _generate_csrf_token}

    @app.before_request
    def _check_csrf_token():
        if request.method in _CSRF_SAFE_METHODS:
            return
        if request.path in _CSRF_EXEMPT_PATHS:
            return
        token = session.get("_csrf_token")
        if not token:
            _generate_csrf_token()
            return
        request_token = request.headers.get("X-CSRFToken") or (
            request.form.get("csrf_token")
            if request.content_type and "form" in request.content_type
            else None
        )
        if not request_token or not secrets.compare_digest(request_token, token):
            return json_error("CSRF token missing or invalid", status=403)


def _setup_rate_limiting(app: Flask) -> None:
    mutate_requests: dict[str, deque] = defaultdict(deque)

    @app.before_request
    def _rate_limit_mutations():
        if request.method in _CSRF_SAFE_METHODS:
            return
        if request.path in _RATE_EXEMPT:
            return
        import time as _time

        addr = request.remote_addr or "unknown"
        now = _time.monotonic()
        dq = mutate_requests[addr]
        while dq and dq[0] < now - _MUTATE_WINDOW:
            dq.popleft()
        if not dq:
            mutate_requests.pop(addr, None)
        if len(dq) >= _MUTATE_MAX:
            return json_error("Rate limit exceeded — try again shortly", status=429)
        mutate_requests[addr].append(now)


def _setup_security_headers(app: Flask) -> None:
    @app.after_request
    def _set_security_headers(response):
        try:
            if _env_bool("INKYPI_REQUEST_TIMING"):
                t0 = getattr(g, "_t0", None)
                if t0 is not None:
                    elapsed_ms = int((perf_counter() - t0) * 1000)
                    logger.info(
                        "HTTP %s %s -> %s in %sms",
                        request.method,
                        request.path,
                        response.status_code,
                        elapsed_ms,
                    )
        except Exception:
            pass

        if request.path.startswith("/static/"):
            if any(
                request.path.endswith(ext)
                for ext in [
                    ".css",
                    ".js",
                    ".png",
                    ".jpg",
                    ".jpeg",
                    ".gif",
                    ".svg",
                    ".woff",
                    ".woff2",
                    ".ttf",
                ]
            ):
                response.headers.setdefault(
                    "Cache-Control",
                    f"public, max-age={_CACHE_1_YEAR}, immutable",
                )
            else:
                response.headers.setdefault(
                    "Cache-Control", f"public, max-age={_CACHE_1_DAY}"
                )

        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        try:
            if (
                request.is_secure
                or request.headers.get("X-Forwarded-Proto", "").lower() == "https"
            ):
                response.headers.setdefault(
                    "Strict-Transport-Security",
                    "max-age=31536000; includeSubDomains",
                )
        except Exception:
            pass
        try:
            csp_value = (
                os.getenv("INKYPI_CSP")
                or "default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline' https://unpkg.com; script-src 'self'; font-src 'self' data: https:"
            )
            report_only = DEV_MODE or _env_bool("INKYPI_CSP_REPORT_ONLY")
            header_name = (
                "Content-Security-Policy-Report-Only"
                if report_only
                else "Content-Security-Policy"
            )
            if header_name not in response.headers:
                response.headers[header_name] = csp_value
        except Exception:
            pass
        try:
            info = pop_hot_reload_info()
            if info and DEV_MODE:
                response.headers.setdefault(
                    "X-InkyPi-Hot-Reload",
                    f"{info['plugin_id']}:{int(info['reloaded'])}",
                )
        except Exception:
            pass
        return response


def _setup_signal_handlers(app: Flask) -> None:
    if is_running_from_reloader():
        return

    def _shutdown_handler(signum, frame):
        sig_name = signal.Signals(signum).name
        logger.info("Received %s — shutting down gracefully", sig_name)
        rt = app.config.get("REFRESH_TASK")
        if rt is not None:
            rt.stop()
        try:
            from utils.http_client import close_http_session

            close_http_session()
        except Exception:
            pass
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _shutdown_handler)
    signal.signal(signal.SIGINT, _shutdown_handler)


def create_app():
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

    device_config = Config()
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

    _setup_secret_key(app, device_config)

    app.config["MAX_FORM_PARTS"] = 10_000
    try:
        _max_len_env = os.getenv("MAX_CONTENT_LENGTH") or os.getenv("MAX_UPLOAD_BYTES")
        _max_len = int(_max_len_env) if _max_len_env else _DEFAULT_MAX_UPLOAD
    except Exception:
        _max_len = _DEFAULT_MAX_UPLOAD
    app.config["MAX_CONTENT_LENGTH"] = _max_len

    _register_blueprints(app)
    _register_health_endpoints(app)

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

    _setup_https_redirect(app)

    @app.before_request
    def _attach_request_id():
        try:
            from utils.http_utils import _get_or_set_request_id

            _get_or_set_request_id()
        except Exception:
            pass

    _setup_csrf_protection(app)
    _setup_rate_limiting(app)
    _register_error_handlers(app)
    _setup_security_headers(app)
    _setup_signal_handlers(app)

    return app


if __name__ == "__main__":
    created_app = main()

    # Guard: mypy knows created_app is Flask; assign to module-level and use local
    app = created_app

    # start the background refresh task (unless running web-only)
    refresh_task_obj = created_app.config.get("REFRESH_TASK")
    if not WEB_ONLY and not is_running_from_reloader() and refresh_task_obj is not None:
        refresh_task_obj.start()
    else:
        logger.info("Web-only mode enabled: background refresh task will not start")

    # display default inkypi image on startup (skip if web-only)
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

    # Notify systemd that the service is ready
    try:
        from cysystemd.daemon import notify as sd_notify

        sd_notify("READY=1")
        logger.info("Notified systemd: READY=1")
    except Exception:
        pass  # Not running under systemd or cysystemd unavailable

    try:
        # Run the Flask app

        # Get local IP address for display (only in dev mode when running on non-Pi)
        if DEV_MODE:
            local_ip = get_ip_address()
            if local_ip:
                logger.info(f"Serving on http://{local_ip}:{PORT}")

        serve(created_app, host="0.0.0.0", port=PORT, threads=1)
    finally:
        refresh_task_obj = created_app.config.get("REFRESH_TASK")
        if refresh_task_obj is not None:
            refresh_task_obj.stop()
