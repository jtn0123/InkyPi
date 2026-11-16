# pyright: reportMissingImports=false
"""Tests for settings update/start-update operations."""

import threading
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from flask.testing import FlaskClient

# ---------------------------------------------------------------------------
# /settings/update (POST) - start update
# ---------------------------------------------------------------------------


class TestStartUpdate:
    def test_start_update_success(
        self, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """POST /settings/update triggers update and returns success JSON."""
        from services import updates

        monkeypatch.setattr(updates, "_systemd_available", lambda: False)
        monkeypatch.setattr(updates, "_get_update_script_path", lambda: None)
        # Prevent the background thread from actually sleeping
        monkeypatch.setattr(
            updates, "_start_update_fallback_thread", lambda sp, target_tag=None: None
        )
        updates._set_update_state(False, None)

        resp = client.post("/settings/update")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["running"] is True
        # Clean up
        updates._set_update_state(False, None)

    def test_start_update_already_running(
        self, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """POST /settings/update returns 409 when update is already running."""
        from services import updates

        # JTN-K3: POST now runs the reaper (``updates._reconcile``) before
        # the conflict guard, which probes systemd for the recorded unit.
        # On CI runners systemd is available but the fake unit name we set
        # below does not exist, so the probe would treat it as "finished"
        # and clear the state — erasing the 409 this test asserts.  Pin
        # the probe to "still running" so we continue to exercise the
        # conflict path without relying on implementation detail of the
        # reaper.
        monkeypatch.setattr(
            updates, "_probe_finished_unit", lambda _unit: (False, False)
        )

        updates._set_update_state(True, "inkypi-update-test.service")
        try:
            resp = client.post("/settings/update")
            assert resp.status_code == 409
            data = resp.get_json()
            assert data["success"] is False
            assert "already in progress" in data["error"]
        finally:
            updates._set_update_state(False, None)

    def test_start_update_systemd_path(
        self, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """POST /settings/update uses systemd path when available."""
        from services import updates

        monkeypatch.setattr(updates, "_systemd_available", lambda: True)
        monkeypatch.setattr(
            updates, "_get_update_script_path", lambda: "/fake/update.sh"
        )
        monkeypatch.setattr(
            updates, "_start_update_via_systemd", lambda target_tag=None: None
        )
        updates._set_update_state(False, None)

        resp = client.post("/settings/update")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        updates._set_update_state(False, None)

    def test_start_update_systemd_fails_falls_back(
        self, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If systemd-run fails, falls back to thread runner."""
        from services import updates

        monkeypatch.setattr(updates, "_systemd_available", lambda: True)
        monkeypatch.setattr(updates, "_get_update_script_path", lambda: None)
        monkeypatch.setattr(
            updates, "_start_update_via_systemd", MagicMock(side_effect=OSError("fail"))
        )
        monkeypatch.setattr(
            updates, "_start_update_fallback_thread", lambda sp, target_tag=None: None
        )
        updates._set_update_state(False, None)

        resp = client.post("/settings/update")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        updates._set_update_state(False, None)

    def test_start_update_toctou_race_prevented(
        self, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Concurrent requests to /settings/update must not both succeed.

        This verifies the TOCTOU fix: the running-flag check and the state
        flip both occur inside the same lock acquisition, so a second request
        racing in between cannot slip through the guard.
        """
        from services import updates

        monkeypatch.setattr(updates, "_systemd_available", lambda: False)
        monkeypatch.setattr(updates, "_get_update_script_path", lambda: None)
        monkeypatch.setattr(
            updates, "_start_update_fallback_thread", lambda sp, target_tag=None: None
        )
        updates._set_update_state(False, None)

        results: list[int] = []
        barrier = threading.Barrier(2)

        def fire() -> None:
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

        updates._set_update_state(False, None)

    def test_state_flip_inside_lock(
        self, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
    ) -> Any:
        """The running flag is set to True while _update_lock is still held.

        We verify atomicity by intercepting the lock's __exit__ and checking
        that _UPDATE_STATE["running"] was already True before the lock released.
        """
        from services import updates

        monkeypatch.setattr(updates, "_systemd_available", lambda: False)
        monkeypatch.setattr(updates, "_get_update_script_path", lambda: None)
        monkeypatch.setattr(
            updates, "_start_update_fallback_thread", lambda sp, target_tag=None: None
        )
        updates._set_update_state(False, None)

        state_at_exit: list[bool] = []
        real_lock = updates._update_lock

        class _CapturingLock:
            """Thin wrapper that records _UPDATE_STATE["running"] on __exit__."""

            def __enter__(self) -> Any:
                real_lock.acquire()
                return self

            def __exit__(self, *args: Any) -> None:
                # Capture the state while still inside the critical section
                state_at_exit.append(bool(updates._UPDATE_STATE.get("running")))
                real_lock.release()

        capturing_lock = _CapturingLock()
        with patch.object(updates, "_update_lock", capturing_lock):
            resp = client.post("/settings/update")

        assert resp.status_code == 200
        # The first __exit__ call (from start_update's `with` block) must see
        # running == True, proving the flip happened inside the lock.
        assert state_at_exit, "Lock __exit__ was never called"
        assert state_at_exit[0] is True, (
            "running flag was not True when the lock was released; "
            "the state flip may have happened outside the lock."
        )

        updates._set_update_state(False, None)


# ---------------------------------------------------------------------------
# /settings/update_status (GET) - update status
# ---------------------------------------------------------------------------


class TestUpdateStatus:
    def test_update_status_idle(
        self, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from services import updates

        updates._set_update_state(False, None)
        resp = client.get("/settings/update_status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["running"] is False
        assert data["unit"] is None

    def test_update_status_running(
        self, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from services import updates

        updates._set_update_state(True, "inkypi-update-123.service")
        # Prevent auto-clear from systemctl checks in CI
        monkeypatch.setattr(updates, "_systemd_available", lambda: False)
        try:
            resp = client.get("/settings/update_status")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["running"] is True
            assert data["unit"] == "inkypi-update-123.service"
            assert data["started_at"] is not None
        finally:
            updates._set_update_state(False, None)

    def test_update_status_clears_when_systemd_inactive(
        self, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When the systemd unit is no longer active, running should auto-clear."""
        from services import updates

        updates._set_update_state(True, "inkypi-update-old.service")
        monkeypatch.setattr(updates, "_systemd_available", lambda: True)
        monkeypatch.setattr(
            updates.subprocess,
            "run",
            lambda *a, **kw: MagicMock(stdout="inactive\n", returncode=0),
        )
        try:
            resp = client.get("/settings/update_status")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["running"] is False
            assert updates._UPDATE_STATE.get("last_unit") == "inkypi-update-old.service"
        finally:
            updates._set_update_state(False, None)

    def test_update_status_timeout_clears(
        self, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If started_at is >30 min ago, update state should auto-clear."""
        from services import updates

        updates._set_update_state(True, None)
        # Backdate started_at by 2 hours
        updates._UPDATE_STATE["started_at"] = time.time() - 7200
        try:
            resp = client.get("/settings/update_status")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["running"] is False
        finally:
            updates._set_update_state(False, None)

    def test_start_update_passes_target_tag(
        self, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """POST /settings/update with target_version should pass it to systemd cmd."""
        from services import updates

        monkeypatch.setattr(updates, "_systemd_available", lambda: True)
        monkeypatch.setattr(
            updates, "_get_update_script_path", lambda: "/fake/do_update.sh"
        )

        captured_args = {}

        def mock_systemd(target_tag: Any = None) -> None:
            captured_args["target_tag"] = target_tag

        monkeypatch.setattr(updates, "_start_update_via_systemd", mock_systemd)
        updates._set_update_state(False, None)

        resp = client.post(
            "/settings/update",
            json={"target_version": "v1.2.0"},
        )
        assert resp.status_code == 200
        assert captured_args["target_tag"] == "v1.2.0"
        updates._set_update_state(False, None)

    def test_start_update_rejects_invalid_target_tag(
        self, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """POST /settings/update rejects shell injection in target_version."""
        from services import updates

        updates._set_update_state(False, None)
        resp = client.post(
            "/settings/update",
            json={"target_version": "; rm -rf /"},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["success"] is False
        assert "Invalid target version" in data["error"]

    def test_start_update_rejects_flag_injection(
        self, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """POST /settings/update rejects flag-style injection."""
        from services import updates

        updates._set_update_state(False, None)
        resp = client.post(
            "/settings/update",
            json={"target_version": "--malicious"},
        )
        assert resp.status_code == 400

    def test_start_update_accepts_semver_with_prerelease(
        self, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """POST /settings/update accepts valid semver with pre-release suffix."""
        from services import updates

        monkeypatch.setattr(updates, "_systemd_available", lambda: True)
        monkeypatch.setattr(
            updates, "_get_update_script_path", lambda: "/fake/do_update.sh"
        )

        captured_args = {}

        def mock_systemd(target_tag: Any = None) -> None:
            captured_args["target_tag"] = target_tag

        monkeypatch.setattr(updates, "_start_update_via_systemd", mock_systemd)
        updates._set_update_state(False, None)

        resp = client.post(
            "/settings/update",
            json={"target_version": "1.0.0-rc1"},
        )
        assert resp.status_code == 200
        assert captured_args["target_tag"] == "1.0.0-rc1"
        updates._set_update_state(False, None)
