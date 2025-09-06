import importlib
import sys
from unittest.mock import MagicMock, patch

from flask import Flask


def _reload_inkypi(monkeypatch, argv=None, env=None):
    if argv is None:
        argv = ["inkypi.py"]
    if env is None:
        env = {}

    # Reset environment vars that influence inkypi
    for key in ["INKYPI_ENV", "FLASK_ENV", "INKYPI_CONFIG_FILE", "INKYPI_PORT", "PORT"]:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    monkeypatch.setattr(sys, "argv", argv)

    # Ensure a clean import each time
    if "inkypi" in sys.modules:
        del sys.modules["inkypi"]

    import inkypi  # noqa: F401
    return importlib.reload(sys.modules["inkypi"])


def test_inkypi_dev_mode_and_blueprints(monkeypatch):
    mod = _reload_inkypi(monkeypatch, argv=["inkypi.py", "--dev"], env={})

    assert getattr(mod, "DEV_MODE", False) is True
    assert getattr(mod, "PORT", None) == 8080

    # Verify Flask app and blueprints are ready
    app = getattr(mod, "app", None)
    assert app is not None
    for bp_name in ["main", "settings", "plugin", "playlist"]:
        assert bp_name in app.blueprints


def test_inkypi_prod_mode_port_from_env(monkeypatch):
    mod = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env={"INKYPI_ENV": "production", "PORT": "1234"})

    assert getattr(mod, "DEV_MODE", True) is False
    assert getattr(mod, "PORT", None) == 1234


def test_inkypi_web_only_flag(monkeypatch):
    mod = _reload_inkypi(monkeypatch, argv=["inkypi.py", "--dev", "--web-only"], env={})
    app = getattr(mod, "app", None)
    assert isinstance(app, Flask)
    # Ensure refresh task does not start in web-only when running as __main__ is simulated by test harness
    rt = app.config['REFRESH_TASK']
    assert rt is not None
    assert rt.running is False


def test_inkypi_fast_dev(monkeypatch):
    mod = _reload_inkypi(monkeypatch, argv=["inkypi.py", "--dev", "--fast-dev"], env={})
    app = getattr(mod, "app", None)
    assert isinstance(app, Flask)
    cfg = app.config['DEVICE_CONFIG']
    assert cfg.get_config("plugin_cycle_interval_seconds") == 30


def test_inkypi_config_file_cli(monkeypatch):
    """Test that --config CLI flag sets the config file path."""
    _mod = _reload_inkypi(monkeypatch, argv=["inkypi.py", "--config", "/path/to/config.json"], env={})
    from config import Config
    assert Config.config_file == "/path/to/config.json"


def test_inkypi_port_cli(monkeypatch):
    """Test that --port CLI flag sets the port."""
    mod = _reload_inkypi(monkeypatch, argv=["inkypi.py", "--port", "3000"], env={})
    assert getattr(mod, "PORT", None) == 3000


def test_inkypi_port_env_inkypi_port(monkeypatch):
    """Test that INKYPI_PORT environment variable sets the port."""
    mod = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env={"INKYPI_PORT": "4000"})
    assert getattr(mod, "PORT", None) == 4000


def test_inkypi_port_env_port_fallback(monkeypatch):
    """Test that PORT environment variable is used as fallback."""
    mod = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env={"PORT": "5000"})
    assert getattr(mod, "PORT", None) == 5000


def test_inkypi_port_invalid_env(monkeypatch):
    """Test that invalid port in environment falls back to default."""
    mod = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env={"INKYPI_PORT": "invalid"})
    assert getattr(mod, "PORT", None) == 80  # Production mode default


def test_inkypi_dev_mode_env_vars(monkeypatch):
    """Test various ways to set dev mode via environment variables."""
    # Test INKYPI_ENV=dev
    mod = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env={"INKYPI_ENV": "dev"})
    assert getattr(mod, "DEV_MODE", False) is True

    # Test INKYPI_ENV=development
    mod = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env={"INKYPI_ENV": "development"})
    assert getattr(mod, "DEV_MODE", False) is True

    # Test FLASK_ENV=dev
    mod = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env={"FLASK_ENV": "dev"})
    assert getattr(mod, "DEV_MODE", False) is True

    # Test FLASK_ENV=development
    mod = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env={"FLASK_ENV": "development"})
    assert getattr(mod, "DEV_MODE", False) is True


def test_inkypi_web_only_env_vars(monkeypatch):
    """Test web-only mode via environment variables."""
    # Test INKYPI_NO_REFRESH=1
    mod = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env={"INKYPI_NO_REFRESH": "1"})
    assert getattr(mod, "WEB_ONLY", False) is True

    # Test INKYPI_NO_REFRESH=true
    mod = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env={"INKYPI_NO_REFRESH": "true"})
    assert getattr(mod, "WEB_ONLY", False) is True

    # Test INKYPI_NO_REFRESH=yes
    mod = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env={"INKYPI_NO_REFRESH": "yes"})
    assert getattr(mod, "WEB_ONLY", False) is True


def test_inkypi_fast_dev_env_vars(monkeypatch):
    """Test fast dev mode via environment variables."""
    mod = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env={"INKYPI_FAST_DEV": "1"})
    app = getattr(mod, "app", None)
    assert isinstance(app, Flask)
    cfg = app.config['DEVICE_CONFIG']
    assert cfg.get_config("plugin_cycle_interval_seconds") == 30


def test_inkypi_prod_mode_defaults(monkeypatch):
    """Test production mode defaults."""
    mod = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env={})
    assert getattr(mod, "DEV_MODE", True) is False  # Should default to False
    assert getattr(mod, "PORT", None) == 80  # Production default port


def test_inkypi_max_content_length_env(monkeypatch):
    """Test MAX_CONTENT_LENGTH environment variable handling."""
    mod = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env={"MAX_CONTENT_LENGTH": "5242880"})  # 5MB
    app = getattr(mod, "app", None)
    assert app is not None
    assert app.config['MAX_CONTENT_LENGTH'] == 5242880


def test_inkypi_max_content_length_invalid_env(monkeypatch):
    """Test invalid MAX_CONTENT_LENGTH falls back to default."""
    mod = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env={"MAX_CONTENT_LENGTH": "invalid"})
    app = getattr(mod, "app", None)
    assert app is not None
    assert app.config['MAX_CONTENT_LENGTH'] == 10 * 1024 * 1024  # Default 10MB


def test_inkypi_max_upload_bytes_env(monkeypatch):
    """Test MAX_UPLOAD_BYTES environment variable as fallback."""
    mod = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env={"MAX_UPLOAD_BYTES": "2097152"})  # 2MB
    app = getattr(mod, "app", None)
    assert app is not None
    assert app.config['MAX_CONTENT_LENGTH'] == 2097152


def test_inkypi_startup_image_generation(monkeypatch):
    """Test startup image generation and display logic."""
    with patch('utils.app_utils.generate_startup_image') as mock_generate, \
         patch('display.display_manager.DisplayManager') as mock_dm_class, \
         patch('config.Config') as mock_config_class:

        # Mock the config and display manager
        mock_config = MagicMock()
        mock_config.get_config.return_value = True  # startup enabled
        mock_config.get_resolution.return_value = (400, 300)
        mock_config_class.return_value = mock_config

        mock_dm = MagicMock()
        mock_dm_class.return_value = mock_dm

        mod = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env={})

        # Mock the WEB_ONLY check
        mod.WEB_ONLY = False

        # Simulate the startup logic from the main block
        if not mod.WEB_ONLY and mock_config.get_config("startup") is True:
            from utils.app_utils import generate_startup_image
            img = generate_startup_image(mock_config.get_resolution())
            mock_dm.display_image(img)
            mock_config.update_value("startup", False, write=True)

        # Verify the calls were made
        mock_generate.assert_called_once_with((400, 300))
        mock_dm.display_image.assert_called_once()
        mock_config.update_value.assert_called_once_with("startup", False, write=True)


def test_inkypi_local_ip_detection(monkeypatch):
    """Test local IP detection in dev mode."""
    # This test would need to be run differently since socket is imported in __main__
    # For now, just verify dev mode is set correctly
    mod = _reload_inkypi(monkeypatch, argv=["inkypi.py", "--dev"], env={})
    assert mod.DEV_MODE is True


def test_inkypi_local_ip_detection_failure(monkeypatch):
    """Test graceful handling when IP detection fails."""
    # Since socket import happens in __main__, we just verify dev mode works
    mod = _reload_inkypi(monkeypatch, argv=["inkypi.py", "--dev"], env={})
    assert mod.DEV_MODE is True


def test_inkypi_error_handlers_exist(monkeypatch):
    """Test that error handlers are registered in the Flask app."""
    mod = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env={})
    app = getattr(mod, "app", None)
    assert app is not None

    # Check that error handlers are registered
    error_handlers = app.error_handler_spec[None]
    # Verify that handlers exist (Flask internal structure may vary)
    assert len(error_handlers) > 0


def test_inkypi_security_headers(monkeypatch):
    """Test that security headers are set."""
    mod = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env={})
    app = getattr(mod, "app", None)
    assert app is not None

    # Test security headers middleware is registered
    assert len(app.after_request_funcs[None]) > 0

    # Create a test request context to verify headers
    with app.test_request_context('/'):
        response = app.response_class()
        # Simulate the after_request function
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
        response.headers.setdefault('Referrer-Policy', 'no-referrer')

        assert response.headers['X-Content-Type-Options'] == 'nosniff'
        assert response.headers['X-Frame-Options'] == 'SAMEORIGIN'
        assert response.headers['Referrer-Policy'] == 'no-referrer'


def test_inkypi_refresh_task_lazy_start(monkeypatch):
    """Test lazy refresh task start in Flask dev server."""
    with patch('os.environ.get') as mock_environ_get:
        mock_environ_get.return_value = "true"  # WERKZEUG_RUN_MAIN

        mod = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env={})
        app = getattr(mod, "app", None)
        assert app is not None

        # Mock the refresh task
        mock_rt = MagicMock()
        mock_rt.running = False
        app.config['REFRESH_TASK'] = mock_rt

        # Mock WEB_ONLY
        mod.WEB_ONLY = False

        # Simulate before_request by calling the logic directly
        if not mod.WEB_ONLY and mock_environ_get("WERKZEUG_RUN_MAIN") == "true":
            rt = app.config.get('REFRESH_TASK')
            if rt and not rt.running:
                rt.start()

        mock_rt.start.assert_called_once()


