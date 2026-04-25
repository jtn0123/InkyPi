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
        mod._VERSION_CACHE["last_error"] = None
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
            assert data["check_succeeded"] is True
            assert data["check_error"] is None
        finally:
            mod._VERSION_CACHE["latest"] = None
            mod._VERSION_CACHE["checked_at"] = 0.0
            mod._VERSION_CACHE["last_error"] = None
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
        mod._VERSION_CACHE["last_error"] = None
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
            assert data["check_succeeded"] is False
            assert data["check_error"]
            # The message should be user-facing and distinguish a network
            # failure from a "rejected tag" outcome (JTN PR #590 review).
            assert data["check_error"].startswith("Couldn't reach GitHub")
            assert "network down" in data["check_error"]
        finally:
            mod._VERSION_CACHE["latest"] = None
            mod._VERSION_CACHE["checked_at"] = 0.0
            mod._VERSION_CACHE["last_error"] = None

    def test_pre_release_tag_is_not_reported_as_network_failure(
        self, client, monkeypatch
    ):
        """A pre-release tag (v1.2.3-rc1) should produce a "not a stable
        release" message, not a misleading "Couldn't reach GitHub" one
        (JTN PR #590 review feedback)."""
        import blueprints.settings as mod

        mod._VERSION_CACHE["latest"] = None
        mod._VERSION_CACHE["checked_at"] = 0.0
        mod._VERSION_CACHE["last_error"] = None

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "tag_name": "v1.2.3-rc1",
            "body": "release candidate",
        }
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr(
            "blueprints.settings.http_get", MagicMock(return_value=mock_resp)
        )

        try:
            resp = client.get("/api/version")
            data = resp.get_json()
            assert data["check_succeeded"] is False
            assert data["check_error"]
            msg = data["check_error"]
            # Must NOT misreport this as a network failure.
            assert "Couldn't reach GitHub" not in msg
            assert "network" not in msg.lower()
            # Should identify the situation accurately.
            assert "stable" in msg.lower()
            assert "v1.2.3-rc1" in msg
        finally:
            mod._VERSION_CACHE["latest"] = None
            mod._VERSION_CACHE["checked_at"] = 0.0
            mod._VERSION_CACHE["last_error"] = None

    def test_force_refresh_bypasses_cache(self, client, monkeypatch):
        """?force=1 must hit the HTTP layer even if a fresh cache entry exists."""
        import blueprints.settings as mod

        mod._VERSION_CACHE["latest"] = "1.0.0"
        mod._VERSION_CACHE["checked_at"] = time.time()
        mod._VERSION_CACHE["release_notes"] = None
        mod._VERSION_CACHE["last_error"] = None

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "tag_name": "v9.9.9",
            "body": "shiny",
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get = MagicMock(return_value=mock_resp)
        monkeypatch.setattr("blueprints.settings.http_get", mock_get)

        try:
            # Cached call should not invoke http_get
            resp = client.get("/api/version")
            assert mock_get.call_count == 0
            assert resp.get_json()["latest"] == "1.0.0"

            # Forced call should ignore the cache and fetch
            resp = client.get("/api/version?force=1")
            assert mock_get.call_count == 1
            data = resp.get_json()
            assert data["latest"] == "9.9.9"
            assert data["check_succeeded"] is True
        finally:
            mod._VERSION_CACHE["latest"] = None
            mod._VERSION_CACHE["checked_at"] = 0.0
            mod._VERSION_CACHE["last_error"] = None
            mod._VERSION_CACHE["release_notes"] = None
