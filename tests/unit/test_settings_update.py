# pyright: reportMissingImports=false
"""Tests for settings update/start-update operations."""

import threading
import time
from unittest.mock import MagicMock, patch

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
        monkeypatch.setattr(
            mod, "_start_update_via_systemd", lambda target_tag=None: None
        )
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

    def test_start_update_toctou_race_prevented(self, client, monkeypatch):
        """Concurrent requests to /settings/update must not both succeed.

        This verifies the TOCTOU fix: the running-flag check and the state
        flip both occur inside the same lock acquisition, so a second request
        racing in between cannot slip through the guard.
        """
        import blueprints.settings as mod

        monkeypatch.setattr(mod, "_systemd_available", lambda: False)
        monkeypatch.setattr(mod, "_get_update_script_path", lambda: None)
        monkeypatch.setattr(
            mod, "_start_update_fallback_thread", lambda sp, target_tag=None: None
        )
        mod._set_update_state(False, None)

        results: list[int] = []
        barrier = threading.Barrier(2)

        def fire():
            barrier.wait()  # both threads hit the endpoint simultaneously
            resp = client.post("/settings/update")
            results.append(resp.status_code)

        t1 = threading.Thread(target=fire)
        t2 = threading.Thread(target=fire)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Exactly one request must succeed (200) and one must be rejected (409).
        results.sort()
        assert results == [200, 409], (
            f"Expected one 200 and one 409 but got {results}; "
            "TOCTOU race may still be present."
        )

        mod._set_update_state(False, None)

    def test_state_flip_inside_lock(self, client, monkeypatch):
        """The running flag is set to True while _update_lock is still held.

        We verify atomicity by intercepting the lock's __exit__ and checking
        that _UPDATE_STATE["running"] was already True before the lock released.
        """
        import blueprints.settings as mod

        monkeypatch.setattr(mod, "_systemd_available", lambda: False)
        monkeypatch.setattr(mod, "_get_update_script_path", lambda: None)
        monkeypatch.setattr(
            mod, "_start_update_fallback_thread", lambda sp, target_tag=None: None
        )
        mod._set_update_state(False, None)

        state_at_exit: list[bool] = []
        real_lock = mod._update_lock

        class _CapturingLock:
            """Thin wrapper that records _UPDATE_STATE["running"] on __exit__."""

            def __enter__(self):
                real_lock.acquire()
                return self

            def __exit__(self, *args):
                # Capture the state while still inside the critical section
                state_at_exit.append(bool(mod._UPDATE_STATE.get("running")))
                real_lock.release()

        capturing_lock = _CapturingLock()
        with patch.object(mod, "_update_lock", capturing_lock):
            resp = client.post("/settings/update")

        assert resp.status_code == 200
        # The first __exit__ call (from start_update's `with` block) must see
        # running == True, proving the flip happened inside the lock.
        assert state_at_exit, "Lock __exit__ was never called"
        assert state_at_exit[0] is True, (
            "running flag was not True when the lock was released; "
            "the state flip may have happened outside the lock."
        )

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

        def mock_systemd(target_tag=None):
            captured_args["target_tag"] = target_tag

        monkeypatch.setattr(mod, "_start_update_via_systemd", mock_systemd)
        mod._set_update_state(False, None)

        resp = client.post(
            "/settings/update",
            json={"target_version": "v1.2.0"},
        )
        assert resp.status_code == 200
        assert captured_args["target_tag"] == "v1.2.0"
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

        def mock_systemd(target_tag=None):
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
