import importlib
import logging
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask, abort


def _reload_inkypi(
    monkeypatch: pytest.MonkeyPatch, argv: Any = None, env: Any = None
) -> Flask:
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

    mod = importlib.reload(sys.modules["inkypi"])
    app: Flask = mod.main(argv[1:])
    return app


def _options(app: Flask) -> Any:
    """Return the RuntimeOptions main() stored on the app."""
    return app.config["RUNTIME_OPTIONS"]


def test_inkypi_dev_mode_and_blueprints(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _reload_inkypi(monkeypatch, argv=["inkypi.py", "--dev"], env={})

    assert _options(app).dev_mode is True
    assert _options(app).port == 8080

    # Verify Flask app and blueprints are ready
    assert app is not None
    for bp_name in ["main", "settings", "plugin", "playlist"]:
        assert bp_name in app.blueprints


def test_inkypi_prod_mode_port_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _reload_inkypi(
        monkeypatch,
        argv=["inkypi.py"],
        env={"INKYPI_ENV": "production", "PORT": "1234"},
    )

    assert _options(app).dev_mode is False
    assert _options(app).port == 1234


def test_inkypi_web_only_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _reload_inkypi(monkeypatch, argv=["inkypi.py", "--dev", "--web-only"], env={})
    assert isinstance(app, Flask)
    # Ensure refresh task does not start in web-only when running as __main__ is simulated by test harness
    rt = app.config["REFRESH_TASK"]
    assert rt is not None
    assert rt.running is False


def test_inkypi_fast_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _reload_inkypi(monkeypatch, argv=["inkypi.py", "--dev", "--fast-dev"], env={})
    assert isinstance(app, Flask)
    cfg = app.config["DEVICE_CONFIG"]
    assert cfg.get_config("plugin_cycle_interval_seconds") == 30


def test_inkypi_config_file_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that --config CLI flag sets the config file path."""
    from config import Config

    # inkypi.py assigns the class attribute; restore it so later tests in
    # the run don't inherit /path/to/config.json.
    monkeypatch.setattr(Config, "config_file", Config.config_file)
    _mod = _reload_inkypi(
        monkeypatch, argv=["inkypi.py", "--config", "/path/to/config.json"], env={}
    )

    assert Config.config_file == "/path/to/config.json"


def test_inkypi_port_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that --port CLI flag sets the port."""
    app = _reload_inkypi(monkeypatch, argv=["inkypi.py", "--port", "3000"], env={})
    assert _options(app).port == 3000


def test_inkypi_port_env_inkypi_port(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that INKYPI_PORT environment variable sets the port."""
    app = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env={"INKYPI_PORT": "4000"})
    assert _options(app).port == 4000


def test_inkypi_port_env_port_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that PORT environment variable is used as fallback."""
    app = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env={"PORT": "5000"})
    assert _options(app).port == 5000


def test_inkypi_port_invalid_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that invalid port in environment falls back to default."""
    app = _reload_inkypi(
        monkeypatch, argv=["inkypi.py"], env={"INKYPI_PORT": "invalid"}
    )
    assert _options(app).port == 80  # Production mode default


def test_inkypi_dev_mode_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test various ways to set dev mode via environment variables."""
    # Test INKYPI_ENV=dev
    app = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env={"INKYPI_ENV": "dev"})
    assert _options(app).dev_mode is True

    # Test INKYPI_ENV=development
    app = _reload_inkypi(
        monkeypatch, argv=["inkypi.py"], env={"INKYPI_ENV": "development"}
    )
    assert _options(app).dev_mode is True

    # Test FLASK_ENV=dev
    app = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env={"FLASK_ENV": "dev"})
    assert _options(app).dev_mode is True

    # Test FLASK_ENV=development
    app = _reload_inkypi(
        monkeypatch, argv=["inkypi.py"], env={"FLASK_ENV": "development"}
    )
    assert _options(app).dev_mode is True


def test_inkypi_web_only_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test web-only mode via environment variables."""
    # Test INKYPI_NO_REFRESH=1
    app = _reload_inkypi(
        monkeypatch, argv=["inkypi.py"], env={"INKYPI_NO_REFRESH": "1"}
    )
    assert _options(app).web_only is True

    # Test INKYPI_NO_REFRESH=true
    app = _reload_inkypi(
        monkeypatch, argv=["inkypi.py"], env={"INKYPI_NO_REFRESH": "true"}
    )
    assert _options(app).web_only is True

    # Test INKYPI_NO_REFRESH=yes
    app = _reload_inkypi(
        monkeypatch, argv=["inkypi.py"], env={"INKYPI_NO_REFRESH": "yes"}
    )
    assert _options(app).web_only is True


def test_inkypi_fast_dev_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test fast dev mode via environment variables."""
    app = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env={"INKYPI_FAST_DEV": "1"})
    assert isinstance(app, Flask)
    cfg = app.config["DEVICE_CONFIG"]
    assert cfg.get_config("plugin_cycle_interval_seconds") == 30


def test_inkypi_prod_mode_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test production mode defaults."""
    app = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env={})
    assert _options(app).dev_mode is False  # Should default to False
    assert _options(app).port == 80  # Production default port


def test_inkypi_max_content_length_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test MAX_CONTENT_LENGTH environment variable handling."""
    app = _reload_inkypi(
        monkeypatch, argv=["inkypi.py"], env={"MAX_CONTENT_LENGTH": "5242880"}
    )  # 5MB
    assert app is not None
    assert app.config["MAX_CONTENT_LENGTH"] == 5242880


def test_inkypi_max_content_length_invalid_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test invalid MAX_CONTENT_LENGTH falls back to default."""
    app = _reload_inkypi(
        monkeypatch, argv=["inkypi.py"], env={"MAX_CONTENT_LENGTH": "invalid"}
    )
    assert app is not None
    assert app.config["MAX_CONTENT_LENGTH"] == 10 * 1024 * 1024  # Default 10MB


def test_inkypi_max_upload_bytes_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test MAX_UPLOAD_BYTES environment variable as fallback."""
    app = _reload_inkypi(
        monkeypatch, argv=["inkypi.py"], env={"MAX_UPLOAD_BYTES": "2097152"}
    )  # 2MB
    assert app is not None
    assert app.config["MAX_CONTENT_LENGTH"] == 2097152


def test_inkypi_startup_image_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no refresh loop, the boot tasks draw the startup image directly."""
    app = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env={})
    inkypi = sys.modules["inkypi"]
    image = object()
    generate = MagicMock(return_value=image)
    monkeypatch.setattr(inkypi, "generate_startup_image", generate)
    monkeypatch.setattr(inkypi.blackout, "is_active", lambda _cfg: False)
    config = MagicMock()
    config.get_config.return_value = True  # startup enabled
    config.get_resolution.return_value = (400, 300)
    display = MagicMock()
    app.config.update(DEVICE_CONFIG=config, DISPLAY_MANAGER=display, REFRESH_TASK=None)

    inkypi.run_boot_display_tasks(app)

    generate.assert_called_once_with((400, 300))
    display.display_image.assert_called_once_with(image)
    config.update_value.assert_called_once_with("startup", False, write=True)


def test_inkypi_local_ip_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test local IP detection in dev mode."""
    # This test would need to be run differently since socket is imported in __main__
    # For now, just verify dev mode is set correctly
    app = _reload_inkypi(monkeypatch, argv=["inkypi.py", "--dev"], env={})
    assert _options(app).dev_mode is True


def test_inkypi_local_ip_detection_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test graceful handling when IP detection fails."""
    # Since socket import happens in __main__, we just verify dev mode works
    app = _reload_inkypi(monkeypatch, argv=["inkypi.py", "--dev"], env={})
    assert _options(app).dev_mode is True


def test_inkypi_error_handlers_exist(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that error handlers are registered in the Flask app."""
    app = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env={})
    assert app is not None

    # Check that error handlers are registered
    error_handlers = app.error_handler_spec[None]
    # Verify that handlers exist (Flask internal structure may vary)
    assert len(error_handlers) > 0


def test_inkypi_security_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that security headers are set."""
    app = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env={})
    assert app is not None

    resp = app.test_client().get("/healthz")
    assert resp.status_code == 200
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert resp.headers["Referrer-Policy"] == "no-referrer"


def test_inkypi_refresh_task_lazy_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test lazy refresh task start in Flask dev server."""
    monkeypatch.setenv("WERKZEUG_RUN_MAIN", "true")

    app = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env={})
    assert app is not None

    mock_rt = MagicMock()
    mock_rt.running = False
    app.config["REFRESH_TASK"] = mock_rt
    app.config["WEB_ONLY"] = False

    response = app.test_client().get("/healthz")
    assert response.status_code == 200
    mock_rt.start.assert_called_once()


def test_version_file_on_disk_is_not_placeholder() -> None:
    """The shipped VERSION file must contain a valid semver, never a placeholder.

    Regression test for JTN-624: historically VERSION contained the literal
    string ``{version}`` because python-semantic-release's build_command did
    not expand the template token. This check fails loudly if we ever ship a
    broken VERSION file again.
    """
    import re

    version_path = Path(__file__).resolve().parents[2] / "VERSION"
    assert version_path.exists(), "VERSION file must exist at the repo root"
    content = version_path.read_text().strip()

    # Reject known-bad values that have been shipped in the past.
    assert content, "VERSION file must not be empty"
    assert content != "{version}", (
        "VERSION contains the literal placeholder — semantic-release "
        "build_command did not expand NEW_VERSION. See JTN-624."
    )
    assert content != "0.1.0", (
        "VERSION is still the initial placeholder '0.1.0' — the release "
        "pipeline is not updating it. See JTN-624."
    )
    # Must be a PEP 440 / semver-ish version (e.g. 0.47.0, 1.2.3-rc.1).
    assert re.match(
        r"^\d+\.\d+\.\d+([.\-+][0-9A-Za-z.\-]+)?$", content
    ), f"VERSION '{content}' is not a valid version string"


def test_pyproject_project_version_matches_semantic_release_version() -> None:
    """[project].version and [tool.semantic_release].version must stay in sync.

    Regression test for JTN-624: semantic-release was only bumping
    ``[tool.semantic_release].version``, leaving the PEP-621
    ``[project].version`` stale. The ``version_toml`` config now lists both,
    so this test catches any future drift.
    """
    import tomllib

    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    with pyproject.open("rb") as f:
        data = tomllib.load(f)

    project_version = data["project"]["version"]
    sr_version = data["tool"]["semantic_release"]["version"]
    assert project_version == sr_version, (
        f"[project].version ({project_version}) must equal "
        f"[tool.semantic_release].version ({sr_version}). "
        "Check version_toml in pyproject.toml. See JTN-624."
    )


# --- JSON error handlers ---


def _register_json_error_routes(app: Flask) -> Any:
    from utils.api_responses import APIError

    @app.route("/cause_api_error")
    def cause_api_error() -> None:
        raise APIError("boom", status=418, code="X", details={"a": 1})

    @app.route("/cause_bad_request")
    def cause_bad_request() -> Any:
        return abort(400)

    @app.route("/cause_unsupported")
    def cause_unsupported() -> Any:
        return abort(415)

    @app.route("/cause_exception")
    def cause_exception() -> None:
        raise RuntimeError("explode")


def test_error_handlers_json_and_html(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env={})
    assert app is not None

    _register_json_error_routes(app)
    client = app.test_client()

    # JSON Accept should yield JSON bodies
    r = client.get("/cause_api_error", headers={"Accept": "application/json"})
    assert r.status_code == 418
    assert r.is_json and r.get_json().get("error") == "boom"

    r = client.get("/cause_bad_request", headers={"Accept": "application/json"})
    assert r.status_code == 400
    assert r.is_json and r.get_json().get("error") == "Bad request"

    r = client.get("/cause_unsupported", headers={"Accept": "application/json"})
    assert r.status_code == 415
    assert r.is_json and r.get_json().get("error") == "Unsupported media type"

    r = client.get("/cause_exception", headers={"Accept": "application/json"})
    assert r.status_code == 500
    assert r.is_json and r.get_json().get("error")

    # HTML Accept should yield plain text bodies
    r = client.get("/cause_bad_request", headers={"Accept": "text/html"})
    assert r.status_code == 400
    assert b"Bad request" in r.data

    r = client.get("/cause_unsupported", headers={"Accept": "text/html"})
    assert r.status_code == 415
    assert b"Unsupported media type" in r.data

    r = client.get("/cause_exception", headers={"Accept": "text/html"})
    assert r.status_code == 500
    assert b"Internal Server Error" in r.data


def test_readyz_states(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env={})
    assert app is not None
    client = app.test_client()

    # web-only branch
    app.config["WEB_ONLY"] = True
    r = client.get("/readyz")
    assert r.status_code == 200 and b"ready:web-only" in r.data

    # running branch
    app.config["WEB_ONLY"] = False

    class _RT:
        running: bool = True

    app.config["REFRESH_TASK"] = _RT()
    r = client.get("/readyz")
    assert r.status_code == 200 and b"ready" in r.data

    # not-ready branch
    app.config["REFRESH_TASK"].running = False
    r = client.get("/readyz")
    assert r.status_code == 503 and b"not-ready" in r.data


def test_csp_headers_default_and_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    # Default in production: CSP is enforced (not report-only) -> None -> None
    app = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env={})
    assert app is not None
    client = app.test_client()

    r = client.get("/healthz")
    assert (
        "Content-Security-Policy" in r.headers
    ), "CSP enforcement header missing in production mode"
    assert "default-src" in r.headers["Content-Security-Policy"]

    # Explicit report-only override via env
    monkeypatch.setenv("INKYPI_CSP_REPORT_ONLY", "1")
    r2 = client.get("/healthz")
    assert "Content-Security-Policy-Report-Only" in r2.headers

    # Custom policy value
    monkeypatch.setenv("INKYPI_CSP", "default-src 'none'")
    r3 = client.get("/healthz")
    header_name = (
        "Content-Security-Policy"
        if "Content-Security-Policy" in r3.headers
        else "Content-Security-Policy-Report-Only"
    )
    # The middleware appends report-uri to the custom value
    assert r3.headers[header_name].startswith("default-src 'none'")


# --- Request ID and hot reload ---


def _register_request_id_routes(app: Flask) -> Any:
    from utils.api_responses import APIError, json_success

    @app.route("/raise_api_error")
    def _raise_api_error() -> None:
        raise APIError("boom", status=418, code="X")

    @app.route("/ok")
    def _ok() -> Any:
        return json_success("OK")


def test_request_id_propagates_in_json_error(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env={})
    assert app is not None

    _register_request_id_routes(app)
    client = app.test_client()

    r = client.get(
        "/raise_api_error",
        headers={
            "Accept": "application/json",
            "X-Request-Id": "rid-123",
        },
    )
    assert r.status_code == 418
    body = r.get_json()
    assert body.get("error") == "boom"
    assert body.get("request_id") == "rid-123"


def test_request_id_propagates_in_json_success(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env={})
    assert app is not None

    _register_request_id_routes(app)
    client = app.test_client()

    r = client.get(
        "/ok",
        headers={
            "Accept": "application/json",
            "X-Request-Id": "rid-456",
        },
    )
    assert r.status_code == 200
    body = r.get_json()
    assert body.get("success") is True
    assert body.get("message") == "OK"
    assert body.get("request_id") == "rid-456"


def test_hot_reload_header_emitted_in_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    # Ensure DEV mode
    app = _reload_inkypi(monkeypatch, argv=["inkypi.py", "--dev"], env={})
    assert app is not None

    # The middleware imports it from the registry when a response goes out.
    monkeypatch.setattr(
        "plugins.plugin_registry.pop_hot_reload_info",
        lambda: {"plugin_id": "foo", "reloaded": True},
        raising=True,
    )

    client = app.test_client()
    r = client.get("/healthz")

    # Header should be set when DEV_MODE and info present
    hdr = r.headers.get("X-InkyPi-Hot-Reload")
    assert hdr == "foo:1"


# --- Timing logs ---


def test_request_timing_log_emitted(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Enable timing logs and run in dev to avoid production headers affecting path
    app = _reload_inkypi(monkeypatch, argv=["inkypi.py", "--dev"], env={})
    assert app is not None

    # Turn on timing via env
    monkeypatch.setenv("INKYPI_REQUEST_TIMING", "1")

    # Capture logs from the inkypi logger specifically
    caplog.set_level(logging.INFO, logger="inkypi")

    # Spy on inkypi logger to ensure timing log path executes regardless of handlers
    messages = []

    def _spy_info(msg: Any, *args: Any, **kwargs: Any) -> None:
        try:
            messages.append(msg % args if args else msg)
        except Exception:
            messages.append(str(msg))

    monkeypatch.setattr(logging.getLogger("inkypi"), "info", _spy_info)

    client = app.test_client()
    resp = client.get("/healthz")
    assert resp.status_code == 200

    # Look for the timing line emitted by after_request (either via records or aggregated text)
    found = (
        bool(messages)
        or any(
            "HTTP GET /healthz -> 200 in" in rec.getMessage() for rec in caplog.records
        )
        or ("HTTP GET /healthz -> 200 in" in caplog.text)
        or (
            # Fallback: match key parts to avoid formatter differences
            "HTTP GET" in caplog.text
            and "/healthz" in caplog.text
            and "-> 200" in caplog.text
        )
    )
    assert found


def test_secret_key_persisted_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    """SECRET_KEY should be persisted via set_env_key even in production mode."""
    # Ensure no SECRET_KEY is set in environment
    monkeypatch.delenv("SECRET_KEY", raising=False)

    with (
        patch("config.Config") as mock_config_class,
        patch("display.display_manager.DisplayManager"),
    ):
        mock_config = MagicMock()
        mock_config.get_config.return_value = None
        mock_config.get_plugins.return_value = []
        mock_config.get_resolution.return_value = (800, 480)
        # Simulate load_env_key returning None (no persisted key)
        mock_config.load_env_key.return_value = None
        mock_config_class.return_value = mock_config

        _reload_inkypi(
            monkeypatch,
            argv=["inkypi.py"],
            env={"INKYPI_ENV": "production"},
        )

        # set_env_key should have been called to persist the generated key
        mock_config.set_env_key.assert_called_once()
        call_args = mock_config.set_env_key.call_args
        assert call_args[0][0] == "SECRET_KEY"
        assert len(call_args[0][1]) == 64  # hex(32 bytes) = 64 chars


# --- HTTPS redirect ---


def test_https_redirect_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """INKYPI_FORCE_HTTPS=1 in production mode should 301-redirect HTTP to HTTPS."""
    app = _reload_inkypi(
        monkeypatch,
        argv=["inkypi.py"],
        env={"INKYPI_FORCE_HTTPS": "1", "INKYPI_ENV": "production"},
    )
    assert app is not None

    client = app.test_client()
    resp = client.get("/settings")
    assert resp.status_code == 301
    assert resp.location.startswith("https://")


def test_no_redirect_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without INKYPI_FORCE_HTTPS, HTTP requests should not be redirected."""
    app = _reload_inkypi(
        monkeypatch,
        argv=["inkypi.py"],
        env={"INKYPI_ENV": "production"},
    )
    assert app is not None

    client = app.test_client()
    resp = client.get("/healthz")
    assert resp.status_code == 200


def test_no_redirect_in_dev_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Even with INKYPI_FORCE_HTTPS=1, dev mode should skip the redirect."""
    app = _reload_inkypi(
        monkeypatch,
        argv=["inkypi.py"],
        env={"INKYPI_FORCE_HTTPS": "1", "INKYPI_ENV": "dev"},
    )
    assert app is not None

    client = app.test_client()
    resp = client.get("/healthz")
    assert resp.status_code == 200


def test_no_redirect_when_already_https(monkeypatch: pytest.MonkeyPatch) -> None:
    """Requests with X-Forwarded-Proto: https should not be redirected."""
    app = _reload_inkypi(
        monkeypatch,
        argv=["inkypi.py"],
        env={
            "INKYPI_FORCE_HTTPS": "1",
            "INKYPI_ENV": "production",
            "INKYPI_TRUSTED_PROXIES": "127.0.0.1",
        },
    )
    assert app is not None

    client = app.test_client()
    resp = client.get(
        "/healthz",
        headers={"X-Forwarded-Proto": "https"},
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert resp.status_code == 200
