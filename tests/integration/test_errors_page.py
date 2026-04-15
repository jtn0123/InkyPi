"""Tests for the /errors page (JTN-586).

Coverage:
- GET /errors returns 200 and renders the page
- The page contains the in-app confirmation modal markup (not window.confirm)
- Clear All button triggers the modal, NOT window.confirm
- POST /errors/clear clears captured reports and returns success
- The JS file does NOT contain window.confirm
"""

from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# GET /errors — page renders
# ---------------------------------------------------------------------------


class TestErrorsPageRender:
    def test_errors_page_returns_200(self, client):
        resp = client.get("/errors")
        assert resp.status_code == 200

    def test_errors_page_has_clear_all_button(self, client):
        resp = client.get("/errors")
        body = resp.data
        assert b"errorsClearBtn" in body

    def test_errors_page_has_in_app_modal(self, client):
        """The page must include the in-app confirm modal, not rely on window.confirm."""
        resp = client.get("/errors")
        body = resp.data
        # Modal container is present
        assert b"clearErrorsModal" in body
        # Modal has a confirm button
        assert b"confirmClearErrorsBtn" in body
        # Modal has a cancel button
        assert b"cancelClearErrorsBtn" in body

    def test_errors_page_modal_message(self, client):
        resp = client.get("/errors")
        body = resp.data
        # Preserves the expected confirmation message from the issue spec
        assert b"Clear all error logs" in body

    def test_errors_page_has_no_window_confirm(self, client):
        """Rendered HTML must NOT call window.confirm anywhere (JTN-586)."""
        resp = client.get("/errors")
        body = resp.data
        assert b"window.confirm" not in body

    def test_errors_page_has_errors_js(self, client):
        resp = client.get("/errors")
        body = resp.data
        assert b"errors_page.js" in body

    def test_errors_page_empty_state_when_no_reports(self, client):
        resp = client.get("/errors")
        body = resp.data
        # Empty state element is present
        assert b"errorsEmptyState" in body


class TestErrorsPageWithReports:
    def test_errors_page_shows_captured_reports(self, client, monkeypatch):
        fake_reports = [
            {
                "level": "error",
                "message": "Something broke",
                "url": "/test",
                "ts": "2026-04-14T12:00:00",
            },
        ]
        import blueprints.errors as errors_mod

        monkeypatch.setattr(errors_mod, "get_captured_reports", lambda: fake_reports)
        resp = client.get("/errors")
        body = resp.data.decode("utf-8")
        assert "Something broke" in body
        assert "error" in body

    def test_errors_page_clear_button_enabled_with_reports(self, client, monkeypatch):
        fake_reports = [
            {"level": "warn", "message": "A warning", "url": "/page", "ts": ""},
        ]
        import blueprints.errors as errors_mod

        monkeypatch.setattr(errors_mod, "get_captured_reports", lambda: fake_reports)
        resp = client.get("/errors")
        body = resp.data
        # Button should NOT have disabled attribute when reports exist
        assert b'id="errorsClearBtn"' in body
        # Check disabled is not adjacent to the button when reports exist
        body_str = body.decode("utf-8")
        # Find the button tag; disabled should not appear right after the id
        import re

        match = re.search(r'id="errorsClearBtn"[^>]*>', body_str)
        assert match, "errorsClearBtn not found"
        assert "disabled" not in match.group(0)


# ---------------------------------------------------------------------------
# POST /errors/clear — action endpoint
# ---------------------------------------------------------------------------


class TestErrorsClearEndpoint:
    def test_clear_returns_200(self, client):
        resp = client.post("/errors/clear")
        assert resp.status_code == 200

    def test_clear_returns_json_success(self, client):
        resp = client.post("/errors/clear")
        data = resp.get_json()
        assert data is not None
        assert data.get("success") is True

    def test_clear_resets_captured_reports(self, client, monkeypatch):
        reset_called = []
        import blueprints.errors as errors_mod

        monkeypatch.setattr(
            errors_mod, "reset_captured_reports", lambda: reset_called.append(True)
        )
        client.post("/errors/clear")
        assert reset_called, "reset_captured_reports was not called"

    def test_clear_requires_post(self, client):
        """GET to /errors/clear should 405 (not found or method not allowed)."""
        resp = client.get("/errors/clear")
        assert resp.status_code in (404, 405)


# ---------------------------------------------------------------------------
# JS file — no window.confirm
# ---------------------------------------------------------------------------


class TestErrorsPageJsNoWindowConfirm:
    def test_errors_page_js_does_not_call_window_confirm(self):
        """The errors_page.js source must NOT contain window.confirm (JTN-586)."""
        js_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "src",
            "static",
            "scripts",
            "errors_page.js",
        )
        js_path = os.path.normpath(js_path)
        assert os.path.isfile(js_path), f"errors_page.js not found at {js_path}"
        with open(js_path, encoding="utf-8") as fh:
            content = fh.read()
        assert (
            "window.confirm" not in content
        ), "errors_page.js must not call window.confirm — use the in-app modal"

    def test_errors_page_js_opens_modal_on_clear(self):
        """errors_page.js must reference the clearErrorsModal (in-app modal)."""
        js_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "src",
            "static",
            "scripts",
            "errors_page.js",
        )
        js_path = os.path.normpath(js_path)
        with open(js_path, encoding="utf-8") as fh:
            content = fh.read()
        assert (
            "clearErrorsModal" in content
        ), "errors_page.js must open the in-app modal (clearErrorsModal)"
