# pyright: reportMissingImports=false
"""Tests for the backend error taxonomy helpers."""

import pytest
from flask import Flask

from utils.backend_errors import (
    ClientInputError,
    InternalOperationError,
    route_error_boundary,
)


@pytest.fixture
def app():
    return Flask(__name__)


def test_client_input_error_adds_field_details():
    err = ClientInputError(
        "Bad input",
        status=422,
        code="validation_error",
        field="plugin_id",
    )

    assert err.status == 422
    assert err.code == "validation_error"
    assert err.details == {"field": "plugin_id"}


def test_internal_operation_error_uses_internal_error_envelope(app):
    with app.app_context():
        err = InternalOperationError(
            "save widget",
            hint="Check filesystem permissions.",
        )
        assert err.status == 500
        assert err.message == "An internal error occurred"
        assert err.code == "internal_error"
        assert err.details == {
            "context": "save widget",
            "hint": "Check filesystem permissions.",
        }


def test_route_error_boundary_wraps_unexpected_errors():
    with pytest.raises(InternalOperationError) as exc_info:
        with route_error_boundary("sync widgets"):
            raise RuntimeError("boom")

    err = exc_info.value
    assert err.code == "internal_error"
    assert err.details == {"context": "sync widgets"}


def test_route_error_boundary_passthroughs_api_errors():
    with pytest.raises(ClientInputError):
        with route_error_boundary("sync widgets"):
            raise ClientInputError("Bad input", status=400)
