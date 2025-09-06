# pyright: reportMissingImports=false
import json
import os
import sys

import pytest
from PIL import Image

# Ensure both project root (for `src.*` imports) and src/ (for top-level `utils`, `display`) are on sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
SRC_ABS = os.path.abspath(os.path.join(PROJECT_ROOT, "src"))
if SRC_ABS not in sys.path:
    sys.path.insert(0, SRC_ABS)


@pytest.fixture(autouse=True)
def mock_screenshot(monkeypatch):
    # Return a simple in-memory image instead of invoking chromium
    def _fake_screenshot(*args, **kwargs):
        dims = args[1] if len(args) > 1 else kwargs.get("dimensions", (800, 480))
        width, height = dims
        img = Image.new("RGB", (width, height), "white")
        return img

    import utils.image_utils as image_utils

    monkeypatch.setattr(image_utils, "take_screenshot", _fake_screenshot, raising=True)
    monkeypatch.setattr(
        image_utils,
        "take_screenshot_html",
        lambda html, dimensions, timeout_ms=None: _fake_screenshot(None, dimensions),
        raising=True,
    )


# (Removed) Autouse requests.get stub to avoid interfering with tests that patch requests explicitly.


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
        "playlist_config": {"playlists": [], "active_playlist": None},
        "refresh_info": {
            "refresh_time": None,
            "image_hash": None,
            "refresh_type": "Manual Update",
            "plugin_id": "",
        },
    }
    config_file = tmp_path / "device.json"
    config_file.write_text(json.dumps(cfg))

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

    from flask import Flask
    from jinja2 import ChoiceLoader, FileSystemLoader

    from blueprints.history import history_bp
    from blueprints.main import main_bp
    from blueprints.playlist import playlist_bp
    from blueprints.plugin import plugin_bp
    from blueprints.settings import settings_bp
    from display.display_manager import DisplayManager
    from plugins.plugin_registry import load_plugins
    from refresh_task import RefreshTask

    app = Flask(__name__)

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
    app.config["MAX_FORM_PARTS"] = 10_000
    # Mirror request size limit from app
    try:
        _max_len_env = os.getenv("MAX_CONTENT_LENGTH") or os.getenv("MAX_UPLOAD_BYTES")
        _max_len = int(_max_len_env) if _max_len_env else 10 * 1024 * 1024
    except Exception:
        _max_len = 10 * 1024 * 1024
    app.config["MAX_CONTENT_LENGTH"] = _max_len

    # Register routes
    app.register_blueprint(main_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(plugin_bp)
    app.register_blueprint(playlist_bp)
    app.register_blueprint(history_bp)
    return app


@pytest.fixture()
def client(flask_app):
    return flask_app.test_client()
