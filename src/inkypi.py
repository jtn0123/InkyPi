#!/usr/bin/env python3

# set up logging
import logging.config
import os

logging.config.fileConfig(os.path.join(os.path.dirname(__file__), 'config', 'logging.conf'))

# suppress warning from inky library https://github.com/pimoroni/inky/issues/205
import warnings

warnings.filterwarnings("ignore", message=".*Busy Wait: Held high.*")

import argparse
import logging
import os
import random

from flask import Flask, request
from jinja2 import ChoiceLoader, FileSystemLoader
from waitress import serve  # type: ignore
from werkzeug.serving import is_running_from_reloader

from blueprints.main import main_bp
from blueprints.playlist import playlist_bp
from blueprints.plugin import plugin_bp
from blueprints.settings import settings_bp
from config import Config
from display.display_manager import DisplayManager
from plugins.plugin_registry import load_plugins
from refresh_task import RefreshTask
from utils.app_utils import generate_startup_image
from utils.http_utils import APIError, json_error, wants_json

logger = logging.getLogger(__name__)

"""CLI and runtime configuration

Options precedence:
1. CLI flags
2. Environment variables (INKYPI_*, PORT)
3. Defaults
"""

# Parse command line arguments
parser = argparse.ArgumentParser(description='InkyPi Display Server')
parser.add_argument('--dev', action='store_true', help='Run in development mode')
parser.add_argument('--config', type=str, default=None, help='Path to device config JSON file')
parser.add_argument('--port', type=int, default=None, help='Port to listen on')
parser.add_argument('--web-only', '--no-refresh', dest='web_only', action='store_true', help='Run web UI only (disable background refresh task)')
parser.add_argument('--fast-dev', action='store_true', help='Use faster refresh intervals and skip startup image in dev')
args, _unknown = parser.parse_known_args()

# Infer DEV_MODE from CLI or environment
env_mode = (os.getenv('INKYPI_ENV', '').strip() or os.getenv('FLASK_ENV', '').strip()).lower()
DEV_MODE = bool(args.dev or env_mode in ('dev', 'development'))

# Toggle for disabling background refresh thread
WEB_ONLY = bool(
    args.web_only or (os.getenv('INKYPI_NO_REFRESH', '').strip().lower() in ('1', 'true', 'yes'))
)

# If --dev explicitly passed, set env var for downstream logic and logs
if args.dev:
    os.environ['INKYPI_ENV'] = 'dev'
    # If explicitly opting for web-only via CLI, mirror it in the environment for downstream logic
    if args.web_only:
        os.environ['INKYPI_NO_REFRESH'] = '1'

# Config file selection via CLI has highest priority; otherwise resolver will decide
if args.config:
    Config.config_file = args.config

# Determine port
if args.port is not None:
    PORT = args.port
else:
    # Prefer env INKYPI_PORT then PORT; default by mode
    env_port = os.getenv('INKYPI_PORT') or os.getenv('PORT')
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
logging.getLogger('waitress.queue').setLevel(logging.ERROR)
FAST_DEV = bool(args.fast_dev or (os.getenv('INKYPI_FAST_DEV', '').strip().lower() in ('1', 'true', 'yes')))

def create_app():
    app = Flask(__name__)
    template_dirs = [
       os.path.join(os.path.dirname(__file__), "templates"),    # Default template folder
       os.path.join(os.path.dirname(__file__), "plugins"),      # Plugin templates
    ]
    app.jinja_loader = ChoiceLoader([FileSystemLoader(directory) for directory in template_dirs])

    device_config = Config()
    display_manager = DisplayManager(device_config)
    refresh_task = RefreshTask(device_config, display_manager)

    # Fast dev tuning: reduce intervals and disable startup image without persisting to disk
    if FAST_DEV:
        try:
            device_config.update_value('plugin_cycle_interval_seconds', 30)
            device_config.update_value('startup', False)
            logger.info('Fast dev mode enabled: plugin cycle set to 30s; startup image disabled')
        except Exception:
            # Best-effort; continue if config lacks these keys
            pass

    load_plugins(device_config.get_plugins())

    # Store dependencies
    app.config['DEVICE_CONFIG'] = device_config
    app.config['DISPLAY_MANAGER'] = display_manager
    app.config['REFRESH_TASK'] = refresh_task

    # Set additional parameters
    app.config['MAX_FORM_PARTS'] = 10_000
    # Enforce maximum request payload size (bytes)
    try:
        _max_len_env = os.getenv('MAX_CONTENT_LENGTH') or os.getenv('MAX_UPLOAD_BYTES')
        _max_len = int(_max_len_env) if _max_len_env else 10 * 1024 * 1024
    except Exception:
        _max_len = 10 * 1024 * 1024
    app.config['MAX_CONTENT_LENGTH'] = _max_len

    # Register Blueprints
    app.register_blueprint(main_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(plugin_bp)
    app.register_blueprint(playlist_bp)
    from blueprints.history import history_bp
    app.register_blueprint(history_bp)

    # If running via Flask dev server, lazily start refresh task on first request
    @app.before_request
    def _ensure_refresh_task_started():
        if WEB_ONLY:
            return
        # Only start in the reloader's main process to avoid double-starts
        if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
            rt = app.config.get('REFRESH_TASK')
            if rt and not rt.running:
                logger.info("Starting refresh task (flask dev server lazy start)")
                rt.start()

    # Consistent JSON error handling
    @app.errorhandler(APIError)
    def _handle_api_error(err: APIError):
        return json_error(err.message, status=err.status, code=err.code, details=err.details)

    @app.errorhandler(400)
    def _handle_bad_request(err):
        if wants_json():
            return json_error("Bad request", status=400)
        return ("Bad request", 400)

    @app.errorhandler(404)
    def _handle_not_found(err):
        if wants_json():
            return json_error("Not found", status=404)
        return ("Not found", 404)

    @app.errorhandler(415)
    def _handle_unsupported_media_type(err):
        if wants_json():
            return json_error("Unsupported media type", status=415)
        return ("Unsupported media type", 415)

    @app.errorhandler(Exception)
    def _handle_unexpected_error(err: Exception):
        try:
            logger.exception("Unhandled exception: %s", err)
        except Exception:
            pass
        if wants_json():
            return json_error("An internal error occurred", status=500)
        return ("Internal Server Error", 500)

    @app.after_request
    def _set_security_headers(response):
        # Basic hardening headers
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
        response.headers.setdefault('Referrer-Policy', 'no-referrer')
        response.headers.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
        # Enable HSTS only when under HTTPS/behind a proxy forwarding HTTPS
        try:
            if request.is_secure or request.headers.get('X-Forwarded-Proto', '').lower() == 'https':
                response.headers.setdefault('Strict-Transport-Security', 'max-age=31536000; includeSubDomains')
        except Exception:
            pass
        return response

    return app

# Module-level app instance for direct execution and tests
app = create_app()

if __name__ == '__main__':

    # start the background refresh task (unless running web-only)
    refresh_task = app.config['REFRESH_TASK']
    if not WEB_ONLY and not is_running_from_reloader():
        refresh_task.start()
    else:
        logger.info('Web-only mode enabled: background refresh task will not start')

    # display default inkypi image on startup (skip if web-only)
    if not WEB_ONLY and app.config['DEVICE_CONFIG'].get_config("startup") is True:
        logger.info("Startup flag is set, displaying startup image")
        device_config = app.config['DEVICE_CONFIG']
        display_manager = app.config['DISPLAY_MANAGER']
        img = generate_startup_image(device_config.get_resolution())
        display_manager.display_image(img)
        device_config.update_value("startup", False, write=True)

    try:
        # Run the Flask app
        app.secret_key = str(random.randint(100000,999999))
        
        # Get local IP address for display (only in dev mode when running on non-Pi)
        if DEV_MODE:
            import socket
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
                s.close()
                logger.info(f"Serving on http://{local_ip}:{PORT}")
            except (OSError, socket.error):
                pass  # Ignore if we can't get the IP
            
        serve(app, host="0.0.0.0", port=PORT, threads=1)
    finally:
        refresh_task = app.config['REFRESH_TASK']
        refresh_task.stop()