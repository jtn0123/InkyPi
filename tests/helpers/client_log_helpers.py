"""Helpers that encapsulate client_log runtime imports for regression tests."""

from __future__ import annotations

import importlib
from types import ModuleType

from flask import Flask


def fresh_client_log_app(monkeypatch=None, *, capture: bool = False) -> tuple[ModuleType, Flask]:
    """Reload ``blueprints.client_log`` and return a fresh module plus app."""
    import blueprints.client_log as cl_mod

    importlib.reload(cl_mod)
    if monkeypatch is not None:
        if capture:
            monkeypatch.setenv("INKYPI_TEST_CAPTURE_CLIENT_LOG", "1")
        else:
            monkeypatch.delenv("INKYPI_TEST_CAPTURE_CLIENT_LOG", raising=False)

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(cl_mod.client_log_bp)
    return cl_mod, app
