import importlib
import os
import sys
from flask import Flask


def _reload_inkypi(monkeypatch, argv=None, env=None):
    if argv is None:
        argv = ["inkypi.py"]
    if env is None:
        env = {}

    # Reset environment vars that influence inkypi
    for key in ["INKYPI_ENV", "FLASK_ENV", "INKYPI_CONFIG_FILE", "INKYPI_PORT", "PORT", "INKYPI_NO_REFRESH"]:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    monkeypatch.setattr(sys, "argv", argv)

    # Ensure a clean import each time
    if "inkypi" in sys.modules:
        del sys.modules["inkypi"]

    import inkypi  # noqa: F401
    return importlib.reload(sys.modules["inkypi"])


def test_create_app_before_request_starts_refresh(monkeypatch):
    # Simulate dev mode but set WERKZEUG_RUN_MAIN so before_request will attempt to start
    mod = _reload_inkypi(monkeypatch, argv=["inkypi.py", "--dev"], env={})
    app = getattr(mod, "app", None)
    assert isinstance(app, Flask)

    # Ensure refresh task exists and is initially not running
    rt = app.config['REFRESH_TASK']
    assert rt is not None
    rt.running = False

    monkeypatch.setenv("WERKZEUG_RUN_MAIN", "true")

    # Call the before_request function by invoking test_request_context
    with app.test_request_context('/'):
        # Trigger before_request functions
        for func in app.before_request_funcs.get(None, []):
            func()

    # After calling, the refresh task should be started (or at least initiated)
    assert rt.running is True


