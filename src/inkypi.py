#!/usr/bin/env python3

# set up logging
import os, logging.config
logging.config.fileConfig(os.path.join(os.path.dirname(__file__), 'config', 'logging.conf'))

# suppress warning from inky library https://github.com/pimoroni/inky/issues/205
import warnings
warnings.filterwarnings("ignore", message=".*Busy Wait: Held high.*")

import os
import random
import time
import sys
import json
import logging
import threading
import argparse
from utils.app_utils import generate_startup_image
from flask import Flask, request
from werkzeug.serving import is_running_from_reloader
from config import Config
from display.display_manager import DisplayManager
from refresh_task import RefreshTask
from blueprints.main import main_bp
from blueprints.settings import settings_bp
from blueprints.plugin import plugin_bp
from blueprints.playlist import playlist_bp
from jinja2 import ChoiceLoader, FileSystemLoader
from plugins.plugin_registry import load_plugins
from waitress import serve  # type: ignore


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
args = parser.parse_args()

# Infer DEV_MODE from CLI or environment
env_mode = (os.getenv('INKYPI_ENV', '').strip() or os.getenv('FLASK_ENV', '').strip()).lower()
DEV_MODE = bool(args.dev or env_mode in ('dev', 'development'))

# If --dev explicitly passed, set env var for downstream logic and logs
if args.dev:
    os.environ['INKYPI_ENV'] = 'dev'

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
app = Flask(__name__)
template_dirs = [
   os.path.join(os.path.dirname(__file__), "templates"),    # Default template folder
   os.path.join(os.path.dirname(__file__), "plugins"),      # Plugin templates
]
app.jinja_loader = ChoiceLoader([FileSystemLoader(directory) for directory in template_dirs])

device_config = Config()
display_manager = DisplayManager(device_config)
refresh_task = RefreshTask(device_config, display_manager)

load_plugins(device_config.get_plugins())

# Store dependencies
app.config['DEVICE_CONFIG'] = device_config
app.config['DISPLAY_MANAGER'] = display_manager
app.config['REFRESH_TASK'] = refresh_task

# Set additional parameters
app.config['MAX_FORM_PARTS'] = 10_000

# Register Blueprints
app.register_blueprint(main_bp)
app.register_blueprint(settings_bp)
app.register_blueprint(plugin_bp)
app.register_blueprint(playlist_bp)

if __name__ == '__main__':

    # start the background refresh task
    refresh_task.start()

    # display default inkypi image on startup
    if device_config.get_config("startup") is True:
        logger.info("Startup flag is set, displaying startup image")
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
            except:
                pass  # Ignore if we can't get the IP
            
        serve(app, host="0.0.0.0", port=PORT, threads=1)
    finally:
        refresh_task.stop()