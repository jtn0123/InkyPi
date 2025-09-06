import importlib
import os
import sys


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


