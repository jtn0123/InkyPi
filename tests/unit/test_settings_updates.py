# pyright: reportMissingImports=false
"""Tests for settings update and version endpoints (_updates.py)."""

import threading
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


class TestUpdateRunnerHelpers:
    def test_run_real_update_passes_target_tag(self, monkeypatch, tmp_path):
        import blueprints.settings as mod

        popen_calls = {}

        class FakeProc:
            stdout = ["line one\n", "line two\n"]
            returncode = 0

            def wait(self):
                return None

        def fake_popen(cmd, **kwargs):
            popen_calls["cmd"] = cmd
            return FakeProc()

        # Place the script under a tmp_path directory and mark it trusted so
        # the validator inside _run_real_update accepts it.
        script = tmp_path / "do_update.sh"
        script.write_text("#!/bin/bash\n")
        trusted = (str(tmp_path.resolve()),)
        monkeypatch.setattr(mod, "_trusted_update_dirs", lambda: trusted)

        log_mock = MagicMock()
        monkeypatch.setattr("blueprints.settings.subprocess.Popen", fake_popen)
        monkeypatch.setattr(mod, "_log_and_publish", log_mock)

        mod._run_real_update(str(script), target_tag="v1.2.3")

        assert popen_calls["cmd"] == ["/bin/bash", str(script.resolve()), "v1.2.3"]
        assert (
            log_mock.call_args_list[-1].args[0] == "web_update: completed successfully"
        )

    def test_run_simulated_update_logs_requested_target_version(self, monkeypatch):
        import blueprints.settings as mod

        log_mock = MagicMock()
        monkeypatch.setattr(mod, "_log_and_publish", log_mock)
        monkeypatch.setattr(
            "blueprints.settings.time.sleep", lambda *_args, **_kwargs: None
        )

        mod._run_simulated_update(target_tag="v9.9.9")

        messages = [call.args[0] for call in log_mock.call_args_list]
        assert "Requested target version: v9.9.9" in messages
        assert messages[0] == "Simulated update starting..."
        assert messages[-1] == "Update completed."

    def test_update_runner_without_script_logs_target_tag(self, monkeypatch):
        import blueprints.settings as mod

        log_mock = MagicMock()
        state_mock = MagicMock()
        monkeypatch.setattr(mod, "_log_and_publish", log_mock)
        monkeypatch.setattr(mod, "_set_update_state", state_mock)
        monkeypatch.setattr(
            "blueprints.settings.time.sleep", lambda *_args, **_kwargs: None
        )

        mod._update_runner(None, target_tag="v2.1.0")

        messages = [call.args[0] for call in log_mock.call_args_list]
        assert "Requested target version: v2.1.0" in messages
        assert messages[-1] == "done (simulated)"
        state_mock.assert_called_once_with(False, None)

    def test_start_update_fallback_thread_passes_target_tag(self, monkeypatch):
        import blueprints.settings as mod

        thread_args = {}

        class FakeThread:
            def __init__(self, target, args, name, daemon):
                thread_args["target"] = target
                thread_args["args"] = args
                thread_args["name"] = name
                thread_args["daemon"] = daemon

            def start(self):
                thread_args["started"] = True

        monkeypatch.setattr("blueprints.settings.threading.Thread", FakeThread)

        mod._start_update_fallback_thread("/fake/do_update.sh", target_tag="v3.0.0")

        assert thread_args["target"] is mod._update_runner
        assert thread_args["args"] == ("/fake/do_update.sh", "v3.0.0")
        assert thread_args["name"] == "update-fallback"
        assert thread_args["daemon"] is True
        assert thread_args["started"] is True


class TestStartUpdateTOCTOURace:
    """Verify that the TOCTOU race in start_update is fixed.

    The check (_UPDATE_STATE["running"]) and the state flip
    (_set_update_state(True, ...)) must happen atomically inside the same
    lock acquisition so two concurrent callers cannot both pass the guard.
    """

    def test_running_state_set_atomically(self, client, monkeypatch):
        """_UPDATE_STATE['running'] is flipped to True while _update_lock is held.

        We intercept the dict __setitem__ to observe whether the lock is held
        at the exact moment the state flip occurs.  This proves the check-and-
        set is atomic and not vulnerable to the TOCTOU window.
        """
        import blueprints.settings as mod

        mod._set_update_state(False, None)
        monkeypatch.setattr(mod, "_systemd_available", lambda: False)
        monkeypatch.setattr(mod, "_get_update_script_path", lambda: None)
        monkeypatch.setattr(
            mod, "_start_update_fallback_thread", lambda sp, target_tag=None: None
        )

        lock_held_when_running_flipped: list[bool] = []
        real_dict = mod._UPDATE_STATE

        class _SpyDict(dict):
            def __setitem__(self, key, value) -> None:
                if key == "running" and value is True:
                    # Record whether the lock is already held (cannot acquire
                    # means this thread already owns it).
                    acquired = mod._update_lock.acquire(blocking=False)
                    if acquired:
                        mod._update_lock.release()
                    lock_held_when_running_flipped.append(not acquired)
                super().__setitem__(key, value)

        spy_state = _SpyDict(real_dict)
        monkeypatch.setattr(mod, "_UPDATE_STATE", spy_state)

        try:
            resp = client.post("/settings/update")
            assert resp.status_code == 200
            assert (
                lock_held_when_running_flipped
            ), "_UPDATE_STATE['running'] was never set to True"
            assert (
                lock_held_when_running_flipped[0] is True
            ), "_UPDATE_STATE['running'] was flipped without holding _update_lock"
        finally:
            mod._set_update_state(False, None)

    def test_concurrent_requests_one_409(self, client, monkeypatch):
        """Two simultaneous start_update calls: exactly one succeeds, one gets 409."""
        import blueprints.settings as mod

        mod._set_update_state(False, None)
        monkeypatch.setattr(mod, "_systemd_available", lambda: False)
        monkeypatch.setattr(mod, "_get_update_script_path", lambda: None)
        monkeypatch.setattr(
            mod, "_start_update_fallback_thread", lambda sp, target_tag=None: None
        )

        results: list[int] = []
        barrier = threading.Barrier(2)

        def make_request():
            barrier.wait()  # both threads hit the endpoint simultaneously
            resp = client.post("/settings/update")
            results.append(resp.status_code)

        try:
            t1 = threading.Thread(target=make_request)
            t2 = threading.Thread(target=make_request)
            t1.start()
            t2.start()
            t1.join(timeout=5)
            t2.join(timeout=5)

            assert sorted(results) == [
                200,
                409,
            ], f"Expected one 200 and one 409, got: {results}"
        finally:
            mod._set_update_state(False, None)


class TestStartUpdateViaSystemdValidation:
    """JTN-319 — hardened systemd-run command construction.

    ``_start_update_via_systemd`` no longer accepts ``unit_name`` or
    ``script_path`` parameters: both are derived from hardcoded constants /
    internal helpers so CodeQL can prove the Popen argv is not user-influenced.
    Only ``target_tag`` survives, and these tests lock in that the regex
    sanitiser at the top of the function rejects every flavour of shell-meta /
    flag-style injection before subprocess.Popen is invoked.
    """

    def _patch_popen_tracker(self, monkeypatch, script_path: str | None = None):
        """Replace subprocess.Popen with a spy that records invocations.

        Also patches ``_validate_update_script_path`` so the test does not
        require the trusted install directories to exist on the test host —
        we only care about the *argv shape* fed to Popen.
        """
        import blueprints.settings as mod

        calls: list[list[str]] = []

        def _fake_popen(cmd, *args, **kwargs):
            calls.append(list(cmd))

            class _FakeProc:
                pass

            return _FakeProc()

        monkeypatch.setattr(mod.subprocess, "Popen", _fake_popen)
        if script_path is not None:
            monkeypatch.setattr(
                mod, "_validate_update_script_path", lambda _p: script_path
            )
            monkeypatch.setattr(mod, "_get_update_script_path", lambda: script_path)
        return calls

    def _redirect_target_version_file(self, monkeypatch, tmp_path):
        monkeypatch.setenv("INKYPI_LOCKFILE_DIR", str(tmp_path))
        return tmp_path / "update-target-version"

    def test_rejects_target_tag_with_shell_injection(self, monkeypatch):
        import pytest

        import blueprints.settings as mod

        calls = self._patch_popen_tracker(
            monkeypatch, "/usr/local/inkypi/install/do_update.sh"
        )
        with pytest.raises(ValueError, match="Invalid target tag"):
            mod._start_update_via_systemd(target_tag="v1.0.0; rm -rf /")
        assert calls == []

    def test_rejects_target_tag_flag_style(self, monkeypatch):
        import pytest

        import blueprints.settings as mod

        calls = self._patch_popen_tracker(
            monkeypatch, "/usr/local/inkypi/install/do_update.sh"
        )
        with pytest.raises(ValueError, match="Invalid target tag"):
            mod._start_update_via_systemd(target_tag="--upload-pack=/tmp/evil")
        assert calls == []

    def test_rejects_target_tag_with_underscores(self, monkeypatch):
        """Underscores must be rejected — Python ``\\w`` would accept them but
        the bash regex in install/do_update.sh does not."""
        import pytest

        import blueprints.settings as mod

        calls = self._patch_popen_tracker(
            monkeypatch, "/usr/local/inkypi/install/do_update.sh"
        )
        with pytest.raises(ValueError, match="Invalid target tag"):
            mod._start_update_via_systemd(target_tag="v1.2.3-rc_1")
        assert calls == []

    def test_accepts_valid_invocation(self, monkeypatch, tmp_path):
        import blueprints.settings as mod

        target_file = self._redirect_target_version_file(monkeypatch, tmp_path)
        calls = self._patch_popen_tracker(
            monkeypatch, "/usr/local/inkypi/install/do_update.sh"
        )
        mod._start_update_via_systemd(target_tag="v0.28.1")
        assert len(calls) == 1
        cmd = calls[0]
        assert cmd[0] == "systemd-run"
        assert "--collect" in cmd
        # Unit name is now hardcoded prefix + a fresh int.
        assert any(arg.startswith("--unit=inkypi-update-") for arg in cmd)
        assert "/bin/bash" in cmd
        assert "/usr/local/inkypi/install/do_update.sh" in cmd
        assert "v0.28.1" not in cmd
        assert target_file.read_text(encoding="utf-8") == "v0.28.1\n"

    def test_accepts_valid_invocation_without_target_tag(self, monkeypatch, tmp_path):
        import blueprints.settings as mod

        target_file = self._redirect_target_version_file(monkeypatch, tmp_path)
        target_file.write_text("v9.9.9\n", encoding="utf-8")
        calls = self._patch_popen_tracker(
            monkeypatch, "/usr/local/inkypi/install/update.sh"
        )
        mod._start_update_via_systemd(target_tag=None)
        assert len(calls) == 1
        cmd = calls[0]
        assert "/usr/local/inkypi/install/update.sh" in cmd
        # target tag must not be appended when None
        assert cmd[-1] == "/usr/local/inkypi/install/update.sh"
        assert not target_file.exists()

    def test_accepts_valid_semver_variants(self, monkeypatch, tmp_path):
        import blueprints.settings as mod

        target_file = self._redirect_target_version_file(monkeypatch, tmp_path)
        calls = self._patch_popen_tracker(
            monkeypatch, "/usr/local/inkypi/install/do_update.sh"
        )
        for tag in ("v0.28.1", "0.28.1", "v1.0.0-beta.1", "2.3.4-rc1"):
            mod._start_update_via_systemd(target_tag=tag)
        assert len(calls) == 4
        for call, tag in zip(
            calls, ("v0.28.1", "0.28.1", "v1.0.0-beta.1", "2.3.4-rc1"), strict=True
        ):
            assert call[-1] == "/usr/local/inkypi/install/do_update.sh"
            assert tag not in call
        assert target_file.read_text(encoding="utf-8") == "2.3.4-rc1\n"

    def test_unit_name_uses_hardcoded_prefix(self, monkeypatch, tmp_path):
        """The systemd unit prefix MUST be the hardcoded ``inkypi-update``
        literal — no caller-controlled value can influence it."""
        import blueprints.settings as mod

        self._redirect_target_version_file(monkeypatch, tmp_path)
        calls = self._patch_popen_tracker(
            monkeypatch, "/usr/local/inkypi/install/do_update.sh"
        )
        mod._start_update_via_systemd(target_tag="v1.2.3")
        assert len(calls) == 1
        unit_args = [arg for arg in calls[0] if arg.startswith("--unit=")]
        assert len(unit_args) == 1
        assert unit_args[0].startswith("--unit=inkypi-update-")
        # Suffix should be a base-10 integer (epoch seconds).
        suffix = unit_args[0].removeprefix("--unit=inkypi-update-")
        assert suffix.isdigit()


class TestValidateUpdateScriptPath:
    """JTN-319 — trusted-root enforcement for the update script realpath.

    These tests cover the standalone validator that
    ``_start_update_via_systemd`` and ``_run_real_update`` both delegate to.
    """

    def test_rejects_path_outside_trusted_root(self, monkeypatch, tmp_path):
        """A do_update.sh basename under /opt/attacker is rejected."""
        import pytest

        import blueprints.settings as mod

        with pytest.raises(ValueError, match="not under trusted root"):
            mod._validate_update_script_path("/opt/attacker/do_update.sh")

    def test_rejects_bad_basename_inside_trusted_root(self, monkeypatch, tmp_path):
        """An evil.sh under a trusted root is still rejected by basename check."""
        import pytest

        import blueprints.settings as mod

        # Force a tmp directory to count as a trusted root so the realpath
        # check passes and the basename check is what fails.
        evil = tmp_path / "evil.sh"
        evil.write_text("#!/bin/bash\necho boom\n")
        monkeypatch.setattr(
            mod, "_trusted_update_dirs", lambda: (str(tmp_path.resolve()),)
        )
        with pytest.raises(ValueError, match="Invalid update script basename"):
            mod._validate_update_script_path(str(evil))

    def test_rejects_path_traversal(self, monkeypatch):
        """``..`` segments are normalised by realpath, then checked against trusted roots."""
        import pytest

        import blueprints.settings as mod

        with pytest.raises(ValueError, match="not under trusted root"):
            mod._validate_update_script_path(
                "/usr/local/inkypi/install/../../etc/passwd"
            )

    def test_rejects_non_string(self, monkeypatch):
        import pytest

        import blueprints.settings as mod

        with pytest.raises(ValueError, match="Invalid update script path"):
            mod._validate_update_script_path(None)  # type: ignore[arg-type]

    def test_rejects_empty_string(self, monkeypatch):
        import pytest

        import blueprints.settings as mod

        with pytest.raises(ValueError, match="Invalid update script path"):
            mod._validate_update_script_path("")

    def test_accepts_path_inside_trusted_root(self, monkeypatch, tmp_path):
        """A do_update.sh inside a fixture-trusted root is returned as realpath."""
        import blueprints.settings as mod

        script = tmp_path / "do_update.sh"
        script.write_text("#!/bin/bash\n")
        trusted = (str(tmp_path.resolve()),)
        monkeypatch.setattr(mod, "_trusted_update_dirs", lambda: trusted)
        result = mod._validate_update_script_path(str(script))
        assert result == str(script.resolve())

    def test_resolves_symlink_to_real_target(self, monkeypatch, tmp_path):
        """Symlinks are followed before the trusted-root check."""
        import blueprints.settings as mod

        real_dir = tmp_path / "real"
        real_dir.mkdir()
        real_script = real_dir / "do_update.sh"
        real_script.write_text("#!/bin/bash\n")
        link_dir = tmp_path / "link"
        link_dir.mkdir()
        link_script = link_dir / "do_update.sh"
        link_script.symlink_to(real_script)
        # Only the *real* directory is trusted; the symlink lives elsewhere.
        monkeypatch.setattr(
            mod, "_trusted_update_dirs", lambda: (str(real_dir.resolve()),)
        )
        result = mod._validate_update_script_path(str(link_script))
        assert result == str(real_script.resolve())

    def test_run_real_update_rejects_bad_script_path(self, monkeypatch):
        """Defense-in-depth: _run_real_update must also validate its inputs.

        Uses a non-temp absolute path that is clearly outside any trusted
        install root so the negative-path semantics are preserved without
        tripping ruff S108 (hardcoded /tmp directory).
        """
        import pytest

        import blueprints.settings as mod

        popen_mock = MagicMock()
        monkeypatch.setattr(mod.subprocess, "Popen", popen_mock)
        with pytest.raises(ValueError, match="Invalid update script path"):
            mod._run_real_update("/opt/attacker/evil.sh", target_tag="v1.0.0")
        popen_mock.assert_not_called()

    def test_run_real_update_rejects_bad_target_tag(self, monkeypatch):
        import pytest

        import blueprints.settings as mod

        popen_mock = MagicMock()
        monkeypatch.setattr(mod.subprocess, "Popen", popen_mock)
        with pytest.raises(ValueError, match="Invalid target tag"):
            mod._run_real_update(
                "/usr/local/inkypi/install/do_update.sh",
                target_tag="v1.0.0; rm -rf /",
            )
        popen_mock.assert_not_called()
