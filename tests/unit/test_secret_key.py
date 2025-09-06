import importlib
import os
import sys


def _write_min_device_config(path):
    import json

    cfg = {
        "name": "InkyPi Test",
        "display_type": "mock",
        "resolution": [800, 480],
        "orientation": "horizontal",
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
    path.write_text(json.dumps(cfg))


def _nop_load_plugins(_conf):
    return None


def test_secret_key_dev_persisted(tmp_path, monkeypatch):
    # Prepare minimal device config and environment
    cfg_path = tmp_path / "device.json"
    _write_min_device_config(cfg_path)
    monkeypatch.setenv("INKYPI_CONFIG_FILE", str(cfg_path))
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("INKYPI_ENV", "dev")
    monkeypatch.delenv("SECRET_KEY", raising=False)

    # Avoid plugin imports during create_app
    import plugins.plugin_registry as pr

    monkeypatch.setattr(pr, "load_plugins", _nop_load_plugins, raising=True)

    # Force fresh import with current env
    sys.modules.pop("inkypi", None)
    inkypi = importlib.import_module("inkypi")

    # SECRET_KEY should be generated and persisted in .env under PROJECT_DIR
    secret = inkypi.app.secret_key
    assert isinstance(secret, str) and len(secret) >= 32

    # Verify persisted
    env_file = tmp_path / ".env"
    assert env_file.exists()
    env_text = env_file.read_text()
    assert "SECRET_KEY=" in env_text
    assert env_text.strip().split("SECRET_KEY=")[-1].strip() != ""


def test_secret_key_prod_ephemeral(tmp_path, monkeypatch):
    # Prepare minimal device config and environment
    cfg_path = tmp_path / "device.json"
    _write_min_device_config(cfg_path)
    monkeypatch.setenv("INKYPI_CONFIG_FILE", str(cfg_path))
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    # Ensure not dev
    monkeypatch.delenv("INKYPI_ENV", raising=False)
    monkeypatch.delenv("FLASK_ENV", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)

    # Mock sys.argv to ensure no --dev flag is present
    monkeypatch.setattr("sys.argv", ["inkypi.py"])

    # Avoid plugin imports during create_app
    import plugins.plugin_registry as pr

    monkeypatch.setattr(pr, "load_plugins", _nop_load_plugins, raising=True)

    # Fresh import
    sys.modules.pop("inkypi", None)
    inkypi = importlib.import_module("inkypi")

    # Verify we're actually in production mode
    assert not inkypi.DEV_MODE, f"DEV_MODE should be False but is {inkypi.DEV_MODE}"
    assert not inkypi.args.dev, f"args.dev should be False but is {inkypi.args.dev}"

    # SECRET_KEY should exist but not be persisted to .env in prod
    secret = inkypi.app.secret_key
    assert isinstance(secret, str) and len(secret) >= 32

    env_file = tmp_path / ".env"
    if env_file.exists():
        env_text = env_file.read_text()
        assert "SECRET_KEY=" not in env_text
    else:
        # .env may not be created at all
        assert True


def _reload_inkypi(monkeypatch, argv=None, env=None):
    if argv is None:
        argv = ["inkypi.py"]
    if env is None:
        env = {}

    # Reset influencing env
    for key in [
        "INKYPI_ENV",
        "FLASK_ENV",
        "INKYPI_CONFIG_FILE",
        "SECRET_KEY",
        "PROJECT_DIR",
    ]:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    monkeypatch.setattr(sys, "argv", argv)

    if "inkypi" in sys.modules:
        del sys.modules["inkypi"]

    import inkypi  # noqa: F401

    return importlib.reload(sys.modules["inkypi"])


def test_secret_key_from_env(monkeypatch, tmp_path):
    # SECRET_KEY present in environment should be used as-is
    mod = _reload_inkypi(
        monkeypatch,
        argv=["inkypi.py", "--dev"],
        env={"SECRET_KEY": "from-env", "PROJECT_DIR": str(tmp_path)},
    )
    app = getattr(mod, "app", None)
    assert app is not None
    assert app.secret_key == "from-env"


def test_secret_key_persisted_in_dev_env_file(monkeypatch, tmp_path):
    # No SECRET_KEY in process env; should generate and persist to .env in dev
    env = {"INKYPI_ENV": "dev", "PROJECT_DIR": str(tmp_path)}
    mod = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env=env)
    app = getattr(mod, "app", None)
    assert app is not None
    generated = app.secret_key
    assert isinstance(generated, str) and len(generated) >= 32

    # Verify persisted in .env
    env_path = os.path.join(str(tmp_path), ".env")
    with open(env_path) as f:
        content = f.read()
    assert f"SECRET_KEY={generated}" in content

    # Reload; should reuse same key from file
    mod2 = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env=env)
    app2 = getattr(mod2, "app", None)
    assert app2 is not None
    assert app2.secret_key == generated


def test_secret_key_ephemeral_in_prod_when_missing(monkeypatch, tmp_path):
    # Production mode: if missing, it should generate but not necessarily persist
    env = {"INKYPI_ENV": "production", "PROJECT_DIR": str(tmp_path)}
    mod = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env=env)
    app = getattr(mod, "app", None)
    assert app is not None
    first = app.secret_key

    # Reload without setting SECRET_KEY; likely different each time
    mod2 = _reload_inkypi(monkeypatch, argv=["inkypi.py"], env=env)
    app2 = getattr(mod2, "app", None)
    assert app2 is not None
    second = app2.secret_key

    assert isinstance(first, str) and isinstance(second, str)
    # They may be equal by chance, but extremely unlikely; allow inequality check
    assert first != second


