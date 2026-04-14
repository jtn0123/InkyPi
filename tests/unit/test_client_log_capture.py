# pyright: reportMissingImports=false
"""Tests for the test-only /api/client-log capture hook (JTN-680, Layer 4).

Goals:
  * Verify the capture is off by default — when the env var is unset the
    handler behaves bit-identical to the pre-JTN-680 implementation (the
    prod path).
  * Verify the capture turns on when ``INKYPI_TEST_CAPTURE_CLIENT_LOG=1``.
  * Verify ``reset_captured_reports`` clears the list between tests.
  * Verify the ``client_log_capture`` integration fixture auto-fails when
    a report is posted during the test.
"""

from __future__ import annotations

import importlib
import json

import pytest
from flask import Flask  # noqa: E402


def _fresh_module(monkeypatch=None, *, capture: bool | None = None):
    """Reload ``blueprints.client_log`` and return (module, Flask app)."""
    import blueprints.client_log as cl_mod

    importlib.reload(cl_mod)
    if monkeypatch is not None:
        if capture is True:
            monkeypatch.setenv("INKYPI_TEST_CAPTURE_CLIENT_LOG", "1")
        elif capture is False:
            monkeypatch.delenv("INKYPI_TEST_CAPTURE_CLIENT_LOG", raising=False)
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(cl_mod.client_log_bp)
    return cl_mod, app


def _post(client, payload):
    return client.post(
        "/api/client-log",
        data=json.dumps(payload),
        content_type="application/json",
    )


class TestCaptureOffByDefault:
    """With the env var unset the handler must match the prod path."""

    def test_env_unset_returns_204_and_no_capture(self, monkeypatch):
        monkeypatch.delenv("INKYPI_TEST_CAPTURE_CLIENT_LOG", raising=False)
        cl_mod, app = _fresh_module(monkeypatch, capture=False)

        resp = _post(app.test_client(), {"level": "warn", "message": "hi"})
        assert resp.status_code == 204
        assert cl_mod.get_captured_reports() == []

    def test_env_empty_string_is_off(self, monkeypatch):
        cl_mod, app = _fresh_module(monkeypatch)
        monkeypatch.setenv("INKYPI_TEST_CAPTURE_CLIENT_LOG", "")

        resp = _post(app.test_client(), {"level": "warn", "message": "hi"})
        assert resp.status_code == 204
        assert cl_mod.get_captured_reports() == []

    def test_env_zero_is_off(self, monkeypatch):
        cl_mod, app = _fresh_module(monkeypatch)
        monkeypatch.setenv("INKYPI_TEST_CAPTURE_CLIENT_LOG", "0")

        resp = _post(app.test_client(), {"level": "error", "message": "x"})
        assert resp.status_code == 204
        assert cl_mod.get_captured_reports() == []


class TestCaptureOn:
    """With the env var set to a truthy value the handler captures reports."""

    def test_env_1_captures_single_report(self, monkeypatch):
        cl_mod, app = _fresh_module(monkeypatch, capture=True)

        resp = _post(app.test_client(), {"level": "error", "message": "boom"})
        assert resp.status_code == 204

        reports = cl_mod.get_captured_reports()
        assert len(reports) == 1
        assert reports[0]["level"] == "error"
        assert reports[0]["message"] == "boom"

    def test_env_true_captures(self, monkeypatch):
        cl_mod, app = _fresh_module(monkeypatch)
        monkeypatch.setenv("INKYPI_TEST_CAPTURE_CLIENT_LOG", "true")

        resp = _post(app.test_client(), {"level": "warn", "message": "m"})
        assert resp.status_code == 204
        assert len(cl_mod.get_captured_reports()) == 1

    def test_env_yes_captures(self, monkeypatch):
        cl_mod, app = _fresh_module(monkeypatch)
        monkeypatch.setenv("INKYPI_TEST_CAPTURE_CLIENT_LOG", "yes")

        resp = _post(app.test_client(), {"level": "warn", "message": "m"})
        assert resp.status_code == 204
        assert len(cl_mod.get_captured_reports()) == 1

    def test_multiple_posts_grow_the_list(self, monkeypatch):
        cl_mod, app = _fresh_module(monkeypatch, capture=True)
        client = app.test_client()

        for i in range(3):
            resp = _post(client, {"level": "warn", "message": f"log-{i}"})
            assert resp.status_code == 204

        reports = cl_mod.get_captured_reports()
        assert len(reports) == 3
        assert [r["message"] for r in reports] == ["log-0", "log-1", "log-2"]

    def test_invalid_report_not_captured(self, monkeypatch):
        """Invalid level returns 400 and must not be captured."""
        cl_mod, app = _fresh_module(monkeypatch, capture=True)

        resp = _post(app.test_client(), {"level": "debug", "message": "x"})
        assert resp.status_code == 400
        assert cl_mod.get_captured_reports() == []

    def test_reset_clears_captured_list(self, monkeypatch):
        cl_mod, app = _fresh_module(monkeypatch, capture=True)
        client = app.test_client()

        _post(client, {"level": "warn", "message": "first"})
        assert len(cl_mod.get_captured_reports()) == 1

        cl_mod.reset_captured_reports()
        assert cl_mod.get_captured_reports() == []

        _post(client, {"level": "warn", "message": "second"})
        reports = cl_mod.get_captured_reports()
        assert len(reports) == 1
        assert reports[0]["message"] == "second"


class TestCapturedReportsIsCopy:
    """get_captured_reports must return a copy; mutating it must not leak."""

    def test_returned_list_is_independent(self, monkeypatch):
        cl_mod, app = _fresh_module(monkeypatch, capture=True)
        _post(app.test_client(), {"level": "warn", "message": "m"})

        snapshot = cl_mod.get_captured_reports()
        snapshot.clear()

        # Underlying list must still have the report
        assert len(cl_mod.get_captured_reports()) == 1


class TestProdPathUnchanged:
    """Explicit regression test: every response-affecting behaviour is
    identical whether capture is on or off. Only the internal list differs.
    """

    @pytest.mark.parametrize(
        ("payload", "expected_status"),
        [
            ({"level": "warn", "message": "ok"}, 204),
            ({"level": "error", "message": "ok"}, 204),
            ({"level": "info", "message": "bad"}, 400),
            ({"message": "no level"}, 400),
        ],
    )
    def test_status_codes_match_with_and_without_capture(
        self, monkeypatch, payload, expected_status
    ):
        # Capture off
        monkeypatch.delenv("INKYPI_TEST_CAPTURE_CLIENT_LOG", raising=False)
        _, app_off = _fresh_module(monkeypatch, capture=False)
        resp_off = _post(app_off.test_client(), payload)

        # Capture on
        _, app_on = _fresh_module(monkeypatch, capture=True)
        resp_on = _post(app_on.test_client(), payload)

        assert resp_off.status_code == expected_status
        assert resp_on.status_code == expected_status

        # Strip the per-response request_id so we compare the stable body.
        def _strip_request_id(data: bytes) -> dict:
            payload = json.loads(data) if data else {}
            payload.pop("request_id", None)
            return payload

        assert _strip_request_id(resp_off.data) == _strip_request_id(resp_on.data)
