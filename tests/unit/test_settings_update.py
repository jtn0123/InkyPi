# pyright: reportMissingImports=false
"""Tests for settings update/start-update operations."""

import time
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# /settings/update (POST) - start update
# ---------------------------------------------------------------------------


class TestStartUpdate:
    def test_start_update_success(self, client, monkeypatch):
        """POST /settings/update triggers update and returns success JSON."""
        import blueprints.settings as mod

        monkeypatch.setattr(mod, "_systemd_available", lambda: False)
        monkeypatch.setattr(mod, "_get_update_script_path", lambda: None)
        # Prevent the background thread from actually sleeping
        monkeypatch.setattr(
            mod, "_start_update_fallback_thread", lambda sp, target_tag=None: None
        )
        mod._set_update_state(False, None)

        resp = client.post("/settings/update")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["running"] is True
        # Clean up
        mod._set_update_state(False, None)

    def test_start_update_already_running(self, client, monkeypatch):
        """POST /settings/update returns 409 when update is already running."""
        import blueprints.settings as mod

        mod._set_update_state(True, "inkypi-update-test.service")
        try:
            resp = client.post("/settings/update")
            assert resp.status_code == 409
            data = resp.get_json()
            assert data["success"] is False
            assert "already in progress" in data["error"]
        finally:
            mod._set_update_state(False, None)

    def test_start_update_systemd_path(self, client, monkeypatch):
        """POST /settings/update uses systemd path when available."""
        import blueprints.settings as mod

        monkeypatch.setattr(mod, "_systemd_available", lambda: True)
        monkeypatch.setattr(mod, "_get_update_script_path", lambda: "/fake/update.sh")
        monkeypatch.setattr(mod, "_start_update_via_systemd", lambda u, s: None)
        mod._set_update_state(False, None)

        resp = client.post("/settings/update")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        mod._set_update_state(False, None)

    def test_start_update_systemd_fails_falls_back(self, client, monkeypatch):
        """If systemd-run fails, falls back to thread runner."""
        import blueprints.settings as mod

        monkeypatch.setattr(mod, "_systemd_available", lambda: True)
        monkeypatch.setattr(mod, "_get_update_script_path", lambda: None)
        monkeypatch.setattr(
            mod, "_start_update_via_systemd", MagicMock(side_effect=OSError("fail"))
        )
        monkeypatch.setattr(
            mod, "_start_update_fallback_thread", lambda sp, target_tag=None: None
        )
        mod._set_update_state(False, None)

        resp = client.post("/settings/update")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        mod._set_update_state(False, None)


# ---------------------------------------------------------------------------
# /settings/update_status (GET) - update status
# ---------------------------------------------------------------------------


class TestUpdateStatus:
    def test_update_status_idle(self, client, monkeypatch):
        import blueprints.settings as mod

        mod._set_update_state(False, None)
        resp = client.get("/settings/update_status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["running"] is False
        assert data["unit"] is None

    def test_update_status_running(self, client, monkeypatch):
        import blueprints.settings as mod

        mod._set_update_state(True, "inkypi-update-123.service")
        # Prevent auto-clear from systemctl checks in CI
        monkeypatch.setattr(mod, "_systemd_available", lambda: False)
        try:
            resp = client.get("/settings/update_status")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["running"] is True
            assert data["unit"] == "inkypi-update-123.service"
            assert data["started_at"] is not None
        finally:
            mod._set_update_state(False, None)

    def test_update_status_clears_when_systemd_inactive(self, client, monkeypatch):
        """When the systemd unit is no longer active, running should auto-clear."""
        import blueprints.settings as mod

        mod._set_update_state(True, "inkypi-update-old.service")
        monkeypatch.setattr(mod, "_systemd_available", lambda: True)
        monkeypatch.setattr(
            mod.subprocess,
            "run",
            lambda *a, **kw: MagicMock(stdout="inactive\n", returncode=0),
        )
        try:
            resp = client.get("/settings/update_status")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["running"] is False
            assert mod._UPDATE_STATE.get("last_unit") == "inkypi-update-old.service"
        finally:
            mod._set_update_state(False, None)

    def test_update_status_timeout_clears(self, client, monkeypatch):
        """If started_at is >30 min ago, update state should auto-clear."""
        import blueprints.settings as mod

        mod._set_update_state(True, None)
        # Backdate started_at by 2 hours
        mod._UPDATE_STATE["started_at"] = time.time() - 7200
        try:
            resp = client.get("/settings/update_status")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["running"] is False
        finally:
            mod._set_update_state(False, None)

    def test_start_update_passes_target_tag(self, client, monkeypatch):
        """POST /settings/update with target_version should pass it to systemd cmd."""
        import blueprints.settings as mod

        monkeypatch.setattr(mod, "_systemd_available", lambda: True)
        monkeypatch.setattr(
            mod, "_get_update_script_path", lambda: "/fake/do_update.sh"
        )

        captured_args = {}

        def mock_systemd(unit, script, target_tag=None):
            captured_args["unit"] = unit
            captured_args["script"] = script
            captured_args["target_tag"] = target_tag

        monkeypatch.setattr(mod, "_start_update_via_systemd", mock_systemd)
        mod._set_update_state(False, None)

        resp = client.post(
            "/settings/update",
            json={"target_version": "v1.2.0"},
        )
        assert resp.status_code == 200
        assert captured_args["target_tag"] == "v1.2.0"
        assert captured_args["script"] == "/fake/do_update.sh"
        mod._set_update_state(False, None)

    def test_start_update_rejects_invalid_target_tag(self, client, monkeypatch):
        """POST /settings/update rejects shell injection in target_version."""
        import blueprints.settings as mod

        mod._set_update_state(False, None)
        resp = client.post(
            "/settings/update",
            json={"target_version": "; rm -rf /"},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["success"] is False
        assert "Invalid target version" in data["error"]

    def test_start_update_rejects_flag_injection(self, client, monkeypatch):
        """POST /settings/update rejects flag-style injection."""
        import blueprints.settings as mod

        mod._set_update_state(False, None)
        resp = client.post(
            "/settings/update",
            json={"target_version": "--malicious"},
        )
        assert resp.status_code == 400

    def test_start_update_accepts_semver_with_prerelease(self, client, monkeypatch):
        """POST /settings/update accepts valid semver with pre-release suffix."""
        import blueprints.settings as mod

        monkeypatch.setattr(mod, "_systemd_available", lambda: True)
        monkeypatch.setattr(
            mod, "_get_update_script_path", lambda: "/fake/do_update.sh"
        )

        captured_args = {}

        def mock_systemd(unit, script, target_tag=None):
            captured_args["target_tag"] = target_tag

        monkeypatch.setattr(mod, "_start_update_via_systemd", mock_systemd)
        mod._set_update_state(False, None)

        resp = client.post(
            "/settings/update",
            json={"target_version": "1.0.0-rc1"},
        )
        assert resp.status_code == 200
        assert captured_args["target_tag"] == "1.0.0-rc1"
        mod._set_update_state(False, None)
