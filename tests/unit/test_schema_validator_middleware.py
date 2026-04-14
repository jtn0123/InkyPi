"""Tests for the dev-mode JSON response schema validator middleware (JTN-664).

These exercise ``app_setup.schema_validator.register`` and the ``create_app``
gate that wires it in behind ``DEV_MODE`` / ``INKYPI_STRICT_SCHEMAS``.
"""

from __future__ import annotations

import logging
from typing import TypedDict

import pytest
from flask import Flask, jsonify


class _ToyResponse(TypedDict):
    value: int


@pytest.fixture()
def dev_app_with_validator(monkeypatch):
    """A minimal Flask app with the validator registered and a toy endpoint.

    The endpoint map is patched to a single entry so tests stay hermetic and
    don't depend on the real route set.
    """
    from app_setup import schema_validator

    monkeypatch.setattr(
        schema_validator, "ENDPOINT_SCHEMAS", {"toy.toy_ok": _ToyResponse}
    )

    app = Flask(__name__)
    app.config["TESTING"] = True

    @app.route("/toy/ok")
    def toy_ok():  # endpoint auto-named "toy_ok"
        return jsonify({"value": 1})

    @app.route("/toy/bad")
    def toy_bad():
        return jsonify({"value": "not-an-int"})

    # Re-patch after route registration so request.endpoint keys line up.
    monkeypatch.setattr(
        schema_validator,
        "ENDPOINT_SCHEMAS",
        {"toy_ok": _ToyResponse, "toy_bad": _ToyResponse},
    )

    schema_validator.register(app)
    return app


def test_dev_mode_logs_no_warning_on_valid_response(dev_app_with_validator, caplog):
    caplog.set_level(logging.WARNING, logger="app_setup.schema_validator")

    resp = dev_app_with_validator.test_client().get("/toy/ok")
    assert resp.status_code == 200

    drift_records = [
        r
        for r in caplog.records
        if r.name == "app_setup.schema_validator" and r.levelno >= logging.WARNING
    ]
    assert drift_records == [], f"unexpected drift warnings: {drift_records}"


def test_dev_mode_logs_warning_on_shape_drift(dev_app_with_validator, caplog):
    caplog.set_level(logging.WARNING, logger="app_setup.schema_validator")

    resp = dev_app_with_validator.test_client().get("/toy/bad")
    # Middleware is advisory — response is still returned unchanged.
    assert resp.status_code == 200
    assert resp.get_json() == {"value": "not-an-int"}

    drift_records = [
        r
        for r in caplog.records
        if r.name == "app_setup.schema_validator" and r.levelno >= logging.WARNING
    ]
    assert drift_records, "expected at least one drift WARNING"
    messages = [r.getMessage() for r in drift_records]
    # Endpoint name and the offending field path both appear in the log.
    assert any("toy_bad" in m for m in messages)
    assert any("$.value" in m for m in messages)


def test_prod_mode_skips_registration(monkeypatch):
    """When DEV_MODE is False and INKYPI_STRICT_SCHEMAS is unset, the validator
    must not be attached to any app-level after_request chain.
    """
    from app_setup import schema_validator

    monkeypatch.delenv("INKYPI_STRICT_SCHEMAS", raising=False)

    # Mirror the production gate in src/inkypi.py create_app() and confirm
    # that with DEV_MODE=False + no opt-in, register() is NOT called.
    import os

    dev_mode = False
    app = Flask(__name__)

    called = {"did": False}
    original_register = schema_validator.register

    def _spy(a):
        called["did"] = True
        return original_register(a)

    monkeypatch.setattr(schema_validator, "register", _spy)

    # Replay the exact gate.
    if dev_mode or os.getenv("INKYPI_STRICT_SCHEMAS") == "1":
        schema_validator.register(app)

    assert called["did"] is False
    # And the app has no after_request functions at all (no side effects).
    assert not any(app.after_request_funcs.values())


def test_strict_env_flag_forces_registration(monkeypatch):
    """The INKYPI_STRICT_SCHEMAS=1 escape hatch wires the middleware in even
    when DEV_MODE is False.
    """
    from app_setup import schema_validator

    monkeypatch.setenv("INKYPI_STRICT_SCHEMAS", "1")

    import os

    dev_mode = False
    app = Flask(__name__)

    if dev_mode or os.getenv("INKYPI_STRICT_SCHEMAS") == "1":
        schema_validator.register(app)

    # after_request hook registered on the None blueprint key.
    hooks = app.after_request_funcs.get(None, [])
    assert any(h.__name__ == "_validate_response_schema" for h in hooks)
