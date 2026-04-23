# pyright: reportMissingImports=false
"""Tests for inline Check for Updates feedback (JTN-352).

Verifies that:
1. The settings page renders a spinner element inside the check-updates button.
2. The /api/version endpoint returns structured version info suitable for
   inline display (current, latest, update_available).
"""

import time
from unittest.mock import MagicMock


class TestCheckUpdatesButtonSpinner:
    """The Check for Updates button must include a .btn-spinner element."""

    def test_settings_page_has_spinner_in_check_button(self, client):
        resp = client.get("/settings")
        assert resp.status_code == 200
        assert b'id="checkUpdatesBtn"' in resp.data
        assert b"btn-spinner" in resp.data

    def test_settings_page_has_update_action_buttons(self, client):
        """The standalone `#updateBadge` chip was removed; the Updates tab
        now exposes the check / start / what's-new trio of buttons only,
        with the sidebar download chip carrying the availability signal."""
        resp = client.get("/settings")
        assert resp.status_code == 200
        assert b'id="updateBadge"' not in resp.data
        assert b'id="startUpdateBtn"' in resp.data
        assert b'id="whatsNewBtn"' in resp.data

    def test_settings_page_has_version_cards(self, client):
        resp = client.get("/settings")
        assert resp.status_code == 200
        assert b'id="currentVersion"' in resp.data
        assert b'id="latestVersion"' in resp.data


class TestApiVersionInlineResult:
    """The /api/version response must include fields for inline display."""

    def test_returns_update_available_field(self, client, monkeypatch):
        import blueprints.settings as mod

        mod._VERSION_CACHE["latest"] = "99.0.0"
        mod._VERSION_CACHE["checked_at"] = time.time()
        mod._VERSION_CACHE["release_notes"] = None
        original_version = client.application.config.get("APP_VERSION")
        try:
            client.application.config["APP_VERSION"] = "1.0.0"
            resp = client.get("/api/version")
            data = resp.get_json()
            assert "update_available" in data
            assert "current" in data
            assert "latest" in data
            assert data["latest"] == "99.0.0"
            assert data["update_available"] is True
        finally:
            mod._VERSION_CACHE["latest"] = None
            mod._VERSION_CACHE["checked_at"] = 0.0
            if original_version is not None:
                client.application.config["APP_VERSION"] = original_version
            else:
                client.application.config.pop("APP_VERSION", None)

    def test_up_to_date_returns_false(self, client, monkeypatch):
        import blueprints.settings as mod

        # Set latest to same as current
        current = client.application.config.get("APP_VERSION", "0.0.1")
        mod._VERSION_CACHE["latest"] = current
        mod._VERSION_CACHE["checked_at"] = time.time()
        mod._VERSION_CACHE["release_notes"] = None
        try:
            resp = client.get("/api/version")
            data = resp.get_json()
            assert data["update_available"] is False
        finally:
            mod._VERSION_CACHE["latest"] = None
            mod._VERSION_CACHE["checked_at"] = 0.0

    def test_includes_release_notes_when_present(self, client, monkeypatch):
        import blueprints.settings as mod

        mod._VERSION_CACHE["latest"] = "99.0.0"
        mod._VERSION_CACHE["checked_at"] = time.time()
        mod._VERSION_CACHE["release_notes"] = "Bug fixes and improvements"
        try:
            resp = client.get("/api/version")
            data = resp.get_json()
            assert data["release_notes"] == "Bug fixes and improvements"
        finally:
            mod._VERSION_CACHE["latest"] = None
            mod._VERSION_CACHE["checked_at"] = 0.0
            mod._VERSION_CACHE["release_notes"] = None

    def test_network_failure_returns_error_gracefully(self, client, monkeypatch):
        import blueprints.settings as mod

        # Force cache miss so it tries to fetch
        mod._VERSION_CACHE["latest"] = None
        mod._VERSION_CACHE["checked_at"] = 0.0
        monkeypatch.setattr(
            "blueprints.settings.http_get",
            MagicMock(side_effect=Exception("network down")),
        )
        try:
            resp = client.get("/api/version")
            # Should still return a valid response (not 500)
            assert resp.status_code == 200
            data = resp.get_json()
            assert "current" in data
        finally:
            mod._VERSION_CACHE["latest"] = None
            mod._VERSION_CACHE["checked_at"] = 0.0
