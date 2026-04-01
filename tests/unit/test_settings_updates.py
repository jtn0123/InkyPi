# pyright: reportMissingImports=false
"""Tests for settings update and version endpoints (_updates.py)."""

import time
from unittest.mock import MagicMock


class TestUpdateStatus:
    def test_systemd_activating_stays_running(self, client, monkeypatch):
        """systemctl is-active returns 'activating' → running stays True."""
        import subprocess

        import blueprints.settings as mod

        mod._set_update_state(True, "inkypi-update-test.service")
        try:
            monkeypatch.setattr(mod, "_systemd_available", lambda: True)
            mock_result = MagicMock()
            mock_result.stdout = "activating\n"
            monkeypatch.setattr(subprocess, "run", MagicMock(return_value=mock_result))

            resp = client.get("/settings/update_status")
            data = resp.get_json()
            assert data["running"] is True
        finally:
            mod._set_update_state(False, None)

    def test_timeout_clears_stale(self, client, monkeypatch):
        """Update started >30 min ago is force-cleared."""
        import blueprints.settings as mod

        mod._set_update_state(True, None)
        # Backdate started_at beyond the timeout
        mod._UPDATE_STATE["started_at"] = time.time() - (
            mod._UPDATE_TIMEOUT_SECONDS + 60
        )
        try:
            resp = client.get("/settings/update_status")
            data = resp.get_json()
            assert data["running"] is False
        finally:
            mod._set_update_state(False, None)

    def test_systemd_check_exception_ignored(self, client, monkeypatch):
        """subprocess.run raises during status check → state not cleared."""
        import subprocess

        import blueprints.settings as mod

        mod._set_update_state(True, "inkypi-update-test.service")
        # Set started_at to recent so timeout doesn't clear it
        mod._UPDATE_STATE["started_at"] = time.time()
        try:
            monkeypatch.setattr(mod, "_systemd_available", lambda: True)
            monkeypatch.setattr(
                subprocess, "run", MagicMock(side_effect=OSError("systemctl failed"))
            )

            resp = client.get("/settings/update_status")
            data = resp.get_json()
            # Still running because the exception was caught
            assert data["running"] is True
        finally:
            mod._set_update_state(False, None)


class TestApiVersion:
    def test_cache_ttl_respected(self, client, monkeypatch):
        """Recent cache entry prevents API call."""
        import blueprints.settings as mod

        mod._VERSION_CACHE["latest"] = "2.0.0"
        mod._VERSION_CACHE["checked_at"] = time.time()  # just now
        mod._VERSION_CACHE["release_notes"] = "notes"
        try:
            # If it tried to call the API, this mock would be invoked
            mock_get = MagicMock(side_effect=AssertionError("should not call API"))
            monkeypatch.setattr("blueprints.settings.http_get", mock_get)

            resp = client.get("/api/version")
            data = resp.get_json()
            assert data["latest"] == "2.0.0"
            mock_get.assert_not_called()
        finally:
            mod._VERSION_CACHE["latest"] = None
            mod._VERSION_CACHE["checked_at"] = 0.0
            mod._VERSION_CACHE["release_notes"] = None

    def test_current_greater_than_latest(self, client, monkeypatch):
        """current > latest → update_available is False."""
        import blueprints.settings as mod

        mod._VERSION_CACHE["latest"] = "1.0.0"
        mod._VERSION_CACHE["checked_at"] = time.time()
        original_version = client.application.config.get("APP_VERSION")
        try:
            with client.application.app_context():
                client.application.config["APP_VERSION"] = "2.0.0"

            resp = client.get("/api/version")
            data = resp.get_json()
            assert data["update_available"] is False
        finally:
            mod._VERSION_CACHE["latest"] = None
            mod._VERSION_CACHE["checked_at"] = 0.0
            if original_version is not None:
                client.application.config["APP_VERSION"] = original_version
            else:
                client.application.config.pop("APP_VERSION", None)

    def test_unknown_current(self, client, monkeypatch):
        """current='unknown' → update_available is False."""
        import blueprints.settings as mod

        mod._VERSION_CACHE["latest"] = "2.0.0"
        mod._VERSION_CACHE["checked_at"] = time.time()
        original_version = client.application.config.get("APP_VERSION")
        try:
            with client.application.app_context():
                client.application.config["APP_VERSION"] = "unknown"

            resp = client.get("/api/version")
            data = resp.get_json()
            assert data["update_available"] is False
        finally:
            mod._VERSION_CACHE["latest"] = None
            mod._VERSION_CACHE["checked_at"] = 0.0
            if original_version is not None:
                client.application.config["APP_VERSION"] = original_version
            else:
                client.application.config.pop("APP_VERSION", None)


class TestSemverGt:
    def test_non_numeric_returns_false(self):
        """Non-numeric version string returns False."""
        import blueprints.settings as mod

        assert mod._semver_gt("abc", "1.0.0") is False

    def test_none_returns_false(self):
        """None input returns False."""
        import blueprints.settings as mod

        assert mod._semver_gt(None, "1.0.0") is False

    def test_equal_returns_false(self):
        """Equal versions return False."""
        import blueprints.settings as mod

        assert mod._semver_gt("1.0.0", "1.0.0") is False

    def test_greater_returns_true(self):
        """Greater version returns True."""
        import blueprints.settings as mod

        assert mod._semver_gt("2.0.0", "1.0.0") is True


class TestStartUpdateEdge:
    def test_no_systemd_uses_thread(self, client, monkeypatch):
        """When systemd is unavailable, falls back to thread runner."""
        import blueprints.settings as mod

        monkeypatch.setattr(mod, "_systemd_available", lambda: False)
        monkeypatch.setattr(mod, "_get_update_script_path", lambda: None)
        fallback_mock = MagicMock()
        monkeypatch.setattr(mod, "_start_update_fallback_thread", fallback_mock)
        mod._set_update_state(False, None)

        try:
            resp = client.post("/settings/update")
            assert resp.status_code == 200
            fallback_mock.assert_called_once()
        finally:
            mod._set_update_state(False, None)

    def test_no_systemd_preserves_target_tag_for_fallback(self, client, monkeypatch):
        """Fallback runner receives the requested target version."""
        import blueprints.settings as mod

        monkeypatch.setattr(mod, "_systemd_available", lambda: False)
        monkeypatch.setattr(mod, "_get_update_script_path", lambda: None)
        fallback_mock = MagicMock()
        monkeypatch.setattr(mod, "_start_update_fallback_thread", fallback_mock)
        mod._set_update_state(False, None)

        try:
            resp = client.post("/settings/update", json={"target_version": "v1.2.3"})
            assert resp.status_code == 200
            fallback_mock.assert_called_once_with(None, target_tag="v1.2.3")
        finally:
            mod._set_update_state(False, None)

    def test_invalid_json_body_returns_400(self, client, monkeypatch):
        """Malformed JSON should be rejected instead of starting an update."""
        import blueprints.settings as mod

        fallback_mock = MagicMock()
        monkeypatch.setattr(mod, "_start_update_fallback_thread", fallback_mock)
        mod._set_update_state(False, None)

        try:
            resp = client.post(
                "/settings/update",
                data='{"target_version":',
                content_type="application/json",
            )
            assert resp.status_code == 400
            data = resp.get_json()
            assert data["success"] is False
            assert data["error"] == "Invalid JSON payload"
            fallback_mock.assert_not_called()
        finally:
            mod._set_update_state(False, None)

    def test_systemd_run_exception_falls_back(self, client, monkeypatch):
        """If systemd-run raises, falls back to thread runner."""
        import blueprints.settings as mod

        monkeypatch.setattr(mod, "_systemd_available", lambda: True)
        monkeypatch.setattr(mod, "_get_update_script_path", lambda: "/fake.sh")
        monkeypatch.setattr(
            mod,
            "_start_update_via_systemd",
            MagicMock(side_effect=RuntimeError("systemd fail")),
        )
        fallback_mock = MagicMock()
        monkeypatch.setattr(mod, "_start_update_fallback_thread", fallback_mock)
        mod._set_update_state(False, None)

        try:
            resp = client.post("/settings/update")
            assert resp.status_code == 200
            fallback_mock.assert_called_once()
        finally:
            mod._set_update_state(False, None)

    def test_systemd_run_exception_preserves_target_tag(self, client, monkeypatch):
        """Systemd fallback still receives the requested target version."""
        import blueprints.settings as mod

        monkeypatch.setattr(mod, "_systemd_available", lambda: True)
        monkeypatch.setattr(mod, "_get_update_script_path", lambda: "/fake.sh")
        monkeypatch.setattr(
            mod,
            "_start_update_via_systemd",
            MagicMock(side_effect=RuntimeError("systemd fail")),
        )
        fallback_mock = MagicMock()
        monkeypatch.setattr(mod, "_start_update_fallback_thread", fallback_mock)
        mod._set_update_state(False, None)

        try:
            resp = client.post("/settings/update", json={"target_version": "v2.0.0"})
            assert resp.status_code == 200
            fallback_mock.assert_called_once_with("/fake.sh", target_tag="v2.0.0")
        finally:
            mod._set_update_state(False, None)
