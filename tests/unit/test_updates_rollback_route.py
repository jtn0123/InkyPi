# pyright: reportMissingImports=false
"""Tests for the rollback route (JTN-708).

Covers:
    * 409 when .last-update-failure is missing
    * 409 when prev_version is missing or malformed
    * 202 Accepted on the happy path
    * systemd-run argv is built from hardcoded constants (regex sanitisation
      defense-in-depth: no caller-controlled values reach Popen)
    * TOCTOU guard — a rollback kicked off while another update is running
      returns 409 instead of both passing the check.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest


def _write_failure(tmp_path, payload: dict | None = None) -> None:
    """Place a .last-update-failure record so the route gate opens."""
    record = payload or {
        "timestamp": "2026-04-14T23:00:00Z",
        "exit_code": 97,
        "last_command": "apt_install",
        "recent_journal_lines": "apt-get: failed",
    }
    (tmp_path / ".last-update-failure").write_text(json.dumps(record), encoding="utf-8")


def _write_prev_version(tmp_path, value: str) -> None:
    (tmp_path / "prev_version").write_text(value, encoding="utf-8")


class TestRollbackGates:
    """The /settings/update/rollback endpoint is gated on two breadcrumbs."""

    def test_rollback_requires_last_failure_present(
        self, client, monkeypatch, tmp_path
    ):
        """Without .last-update-failure, rollback is refused with 409."""
        import blueprints.settings as mod

        monkeypatch.setenv("INKYPI_LOCKFILE_DIR", str(tmp_path))
        # prev_version IS present, but no failure file → must still reject.
        _write_prev_version(tmp_path, "v0.52.0")
        mod._set_update_state(False, None)

        try:
            resp = client.post("/settings/update/rollback")
            assert resp.status_code == 409
            data = resp.get_json()
            assert data["success"] is False
            assert data["code"] == "no_failure"
        finally:
            mod._set_update_state(False, None)

    def test_rollback_requires_prev_version_present(
        self, client, monkeypatch, tmp_path
    ):
        """With a failure recorded but no prev_version, rollback is refused."""
        import blueprints.settings as mod

        monkeypatch.setenv("INKYPI_LOCKFILE_DIR", str(tmp_path))
        _write_failure(tmp_path)
        # Do NOT write prev_version — the file simply doesn't exist.
        mod._set_update_state(False, None)

        try:
            resp = client.post("/settings/update/rollback")
            assert resp.status_code == 409
            data = resp.get_json()
            assert data["success"] is False
            assert data["code"] == "no_prev_version"
        finally:
            mod._set_update_state(False, None)

    def test_rollback_refuses_malformed_prev_version(
        self, client, monkeypatch, tmp_path
    ):
        """A corrupt prev_version (non-semver) must not trigger a rollback."""
        import blueprints.settings as mod

        monkeypatch.setenv("INKYPI_LOCKFILE_DIR", str(tmp_path))
        _write_failure(tmp_path)
        # Shell-injection attempt / arbitrary string
        _write_prev_version(tmp_path, "; rm -rf /")
        mod._set_update_state(False, None)

        try:
            resp = client.post("/settings/update/rollback")
            assert resp.status_code == 409
            data = resp.get_json()
            assert data["code"] == "no_prev_version"
        finally:
            mod._set_update_state(False, None)


class TestRollbackHappyPath:
    """Happy-path rollback returns 202 Accepted and schedules the script."""

    def test_rollback_endpoint_returns_202_on_success(
        self, client, monkeypatch, tmp_path
    ):
        import blueprints.settings as mod

        monkeypatch.setenv("INKYPI_LOCKFILE_DIR", str(tmp_path))
        _write_failure(tmp_path)
        _write_prev_version(tmp_path, "v0.52.0")
        mod._set_update_state(False, None)

        monkeypatch.setattr(mod, "_systemd_available", lambda: True)
        spy = MagicMock()
        monkeypatch.setattr(mod, "_start_rollback_via_systemd", spy)

        try:
            resp = client.post("/settings/update/rollback")
            assert resp.status_code == 202, resp.get_json()
            data = resp.get_json()
            assert data["success"] is True
            assert data["running"] is True
            assert data["target_version"] == "v0.52.0"
            spy.assert_called_once()
            # running flag must be set so a concurrent update is refused
            assert mod._UPDATE_STATE["running"] is True
        finally:
            mod._set_update_state(False, None)

    def test_rollback_endpoint_falls_back_without_systemd(
        self, client, monkeypatch, tmp_path
    ):
        """On dev/macOS without systemd-run, the fallback thread runner runs."""
        import blueprints.settings as mod

        monkeypatch.setenv("INKYPI_LOCKFILE_DIR", str(tmp_path))
        _write_failure(tmp_path)
        _write_prev_version(tmp_path, "v0.52.0")
        mod._set_update_state(False, None)

        monkeypatch.setattr(mod, "_systemd_available", lambda: False)
        fallback = MagicMock()
        monkeypatch.setattr(mod, "_start_update_fallback_thread", fallback)

        try:
            resp = client.post("/settings/update/rollback")
            assert resp.status_code == 202
            fallback.assert_called_once_with(None, target_tag="v0.52.0")
        finally:
            mod._set_update_state(False, None)

    def test_rollback_refuses_when_update_already_running(
        self, client, monkeypatch, tmp_path
    ):
        """TOCTOU: rollback and a concurrent update cannot both pass."""
        import blueprints.settings as mod

        monkeypatch.setenv("INKYPI_LOCKFILE_DIR", str(tmp_path))
        _write_failure(tmp_path)
        _write_prev_version(tmp_path, "v0.52.0")
        mod._set_update_state(True, "inkypi-update-busy.service")

        try:
            resp = client.post("/settings/update/rollback")
            assert resp.status_code == 409
            data = resp.get_json()
            assert data["running"] is True
        finally:
            mod._set_update_state(False, None)


class TestRollbackSanitization:
    """JTN-708 / JTN-319 parity: argv built from hardcoded constants only."""

    def test_rollback_route_sanitizes_version_before_systemd_run(
        self, client, monkeypatch, tmp_path
    ):
        """systemd-run argv contains only validated / literal values.

        Even though the route derives the target version from the
        prev_version file (not user input), the regex sanitiser at the top
        of ``_start_rollback_via_systemd`` must still reject anything that
        failed ``_TAG_RE`` — the prev_version guard already gates the
        route, so here we additionally verify the argv structure and that a
        crafted breadcrumb never reaches Popen.
        """
        import blueprints.settings as mod

        monkeypatch.setenv("INKYPI_LOCKFILE_DIR", str(tmp_path))
        _write_failure(tmp_path)
        # Crafted prev_version that would pass a loose regex but fail _TAG_RE
        # (underscores are rejected — see test_rejects_target_tag_with_underscores
        # in test_settings_updates.py).
        _write_prev_version(tmp_path, "v1.2.3-rc_1")
        mod._set_update_state(False, None)

        monkeypatch.setattr(mod, "_systemd_available", lambda: True)
        spy = MagicMock()
        monkeypatch.setattr(mod, "_start_rollback_via_systemd", spy)

        try:
            resp = client.post("/settings/update/rollback")
            # _read_prev_version applied _TAG_RE and returned None →
            # route refuses with 409 / no_prev_version; Popen is never reached.
            assert resp.status_code == 409
            assert resp.get_json()["code"] == "no_prev_version"
            spy.assert_not_called()
        finally:
            mod._set_update_state(False, None)

    def test_start_rollback_via_systemd_argv_is_hardcoded(self, monkeypatch, tmp_path):
        """argv has the expected shape: literal prefix + canonical script path."""
        import blueprints.settings as mod

        calls: list[list[str]] = []

        def _fake_popen(cmd, *args, **kwargs):
            calls.append(list(cmd))

            class _FakeProc:
                pass

            return _FakeProc()

        monkeypatch.setattr(mod.subprocess, "Popen", _fake_popen)
        # Bypass trusted-root filesystem check — we only care about argv shape.
        monkeypatch.setattr(
            mod,
            "_validate_rollback_script_path",
            lambda _p: "/usr/local/inkypi/install/rollback.sh",
        )
        monkeypatch.setattr(
            mod,
            "_get_rollback_script_path",
            lambda: "/usr/local/inkypi/install/rollback.sh",
        )

        mod._start_rollback_via_systemd()

        assert len(calls) == 1
        cmd = calls[0]
        assert cmd[0] == "systemd-run"
        assert "--collect" in cmd
        unit_args = [arg for arg in cmd if arg.startswith("--unit=")]
        assert len(unit_args) == 1
        assert unit_args[0].startswith("--unit=inkypi-rollback-")
        suffix = unit_args[0].removeprefix("--unit=inkypi-rollback-")
        assert suffix.isdigit()
        assert "/bin/bash" in cmd
        assert "/usr/local/inkypi/install/rollback.sh" in cmd
        # rollback.sh takes no arguments — nothing after the script path.
        assert cmd[-1] == "/usr/local/inkypi/install/rollback.sh"


class TestValidateRollbackScriptPath:
    """Trusted-root enforcement — parity with _validate_update_script_path."""

    def test_rejects_path_outside_trusted_root(self, monkeypatch, tmp_path):
        import blueprints.settings as mod

        with pytest.raises(ValueError, match="not under trusted root"):
            mod._validate_rollback_script_path("/opt/attacker/rollback.sh")

    def test_rejects_wrong_basename_under_trusted_root(self, monkeypatch, tmp_path):
        """do_update.sh under a trusted root must NOT be execable as rollback."""
        import blueprints.settings as mod

        # mod.__file__ is src/blueprints/settings/__init__.py → repo root is parents[3].
        repo_install = (
            __import__("pathlib")
            .Path(mod.__file__)
            .resolve()
            .parents[3]
            .joinpath("install")
        )
        legitimate = str(repo_install / "do_update.sh")
        with pytest.raises(ValueError, match="Invalid rollback script basename"):
            mod._validate_rollback_script_path(legitimate)

    def test_accepts_repo_relative_rollback_script(self):
        import blueprints.settings as mod

        # mod.__file__ is src/blueprints/settings/__init__.py → repo root is parents[3].
        repo_install = (
            __import__("pathlib")
            .Path(mod.__file__)
            .resolve()
            .parents[3]
            .joinpath("install")
        )
        script = str(repo_install / "rollback.sh")
        # Will raise if the file isn't under a trusted root, which we set up
        # by virtue of the repo-relative trusted-dirs entry.
        assert mod._validate_rollback_script_path(script).endswith(
            "install/rollback.sh"
        )


class TestGetRollbackScriptPath:
    """Cover the candidate-cascade helper that resolves rollback.sh."""

    def test_finds_repo_relative_script(self, monkeypatch):
        """Developer environment: picks up install/rollback.sh via parents[3]."""
        import blueprints.settings as mod

        # Clear PROJECT_DIR so the helper falls through to the repo-relative
        # path (the repo-relative lookup is always the last candidate).
        monkeypatch.delenv("PROJECT_DIR", raising=False)
        path = mod._get_rollback_script_path()
        # In the repo-under-test, install/rollback.sh exists — confirm the
        # helper finds it and returns an absolute path.
        assert path is not None
        assert path.endswith("install/rollback.sh")

    def test_returns_none_when_no_candidate_exists(self, monkeypatch, tmp_path):
        """No PROJECT_DIR + no script on disk → None (caller decides)."""
        import blueprints.settings as mod

        monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
        # Also short-circuit the repo-relative fallback by pointing
        # ``__file__`` resolution at a tmp tree that has no rollback.sh.
        # We can't easily rewrite __file__ here, so instead verify by
        # temporarily renaming the file — but renaming risks test pollution.
        # Simpler: just patch os.path.isfile to always return False so every
        # candidate is rejected, isolating the helper's "nothing found" branch.
        monkeypatch.setattr(mod.os.path, "isfile", lambda _p: False)
        assert mod._get_rollback_script_path() is None

    def test_honors_project_dir_with_symlinked_src(self, monkeypatch, tmp_path):
        """Production layout: PROJECT_DIR/src → repo/src (symlink) resolves."""
        import blueprints.settings as mod

        # Build a fake repo tree with an install/ dir holding rollback.sh.
        repo = tmp_path / "repo"
        (repo / "install").mkdir(parents=True)
        script = repo / "install" / "rollback.sh"
        script.write_text("#!/bin/bash\n")
        # Build the production layout under project_dir: project_dir/src → repo/src.
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        (repo / "src").mkdir()
        (project_dir / "src").symlink_to(repo / "src")

        monkeypatch.setenv("PROJECT_DIR", str(project_dir))
        resolved = mod._get_rollback_script_path()
        assert resolved == str(script)


class TestStartRollbackViaSystemdFullPath:
    """End-to-end coverage of _start_rollback_via_systemd with Popen mocked."""

    def test_popen_invoked_with_project_dir_override(self, monkeypatch, tmp_path):
        """PROJECT_DIR env override flows into --setenv argv element."""
        import blueprints.settings as mod

        # Build a fake trusted-root layout under tmp_path and monkeypatch
        # _trusted_update_dirs so the realpath check accepts our fixture.
        install_dir = tmp_path / "install"
        install_dir.mkdir()
        script = install_dir / "rollback.sh"
        script.write_text("#!/bin/bash\n")

        monkeypatch.setattr(mod, "_trusted_update_dirs", lambda: (str(install_dir),))
        monkeypatch.setattr(mod, "_get_rollback_script_path", lambda: str(script))

        calls: list[list[str]] = []

        def _fake_popen(cmd, *args, **kwargs):
            calls.append(list(cmd))

            class _FakeProc:
                pass

            return _FakeProc()

        monkeypatch.setattr(mod.subprocess, "Popen", _fake_popen)

        # Set a valid PROJECT_DIR that matches the absolute-POSIX regex.
        monkeypatch.setenv("PROJECT_DIR", "/opt/inkypi")
        mod._start_rollback_via_systemd()

        assert len(calls) == 1
        argv = calls[0]
        assert "--setenv=PROJECT_DIR=/opt/inkypi" in argv
        assert str(script) in argv

    def test_popen_invoked_with_malformed_project_dir_falls_back(
        self, monkeypatch, tmp_path
    ):
        """A PROJECT_DIR with ``..`` traversal falls back to the default."""
        import blueprints.settings as mod

        install_dir = tmp_path / "install"
        install_dir.mkdir()
        script = install_dir / "rollback.sh"
        script.write_text("#!/bin/bash\n")

        monkeypatch.setattr(mod, "_trusted_update_dirs", lambda: (str(install_dir),))
        monkeypatch.setattr(mod, "_get_rollback_script_path", lambda: str(script))

        calls: list[list[str]] = []

        def _fake_popen(cmd, *args, **kwargs):
            calls.append(list(cmd))
            return type("P", (), {})()

        monkeypatch.setattr(mod.subprocess, "Popen", _fake_popen)

        # ``..`` traversal — must be rejected and replaced with default.
        monkeypatch.setenv("PROJECT_DIR", "/opt/../etc")
        mod._start_rollback_via_systemd()

        argv = calls[0]
        assert "--setenv=PROJECT_DIR=/usr/local/inkypi" in argv


class TestRollbackRouteErrorPaths:
    """Outer-except branches that don't fire in the happy path."""

    def test_rollback_route_handles_systemd_run_exception(
        self, client, monkeypatch, tmp_path
    ):
        """If _start_rollback_via_systemd throws, state is cleared + 500 returned."""
        import blueprints.settings as mod

        monkeypatch.setenv("INKYPI_LOCKFILE_DIR", str(tmp_path))
        _write_failure(tmp_path)
        _write_prev_version(tmp_path, "v0.52.0")
        mod._set_update_state(False, None)

        monkeypatch.setattr(mod, "_systemd_available", lambda: True)

        def _boom():
            raise OSError("systemd-run missing")

        monkeypatch.setattr(mod, "_start_rollback_via_systemd", _boom)

        try:
            resp = client.post("/settings/update/rollback")
            assert resp.status_code == 500
            body = resp.get_json()
            assert body["error"] == "An internal error occurred"
            assert body["code"] == "internal_error"
            assert body["details"]["context"] == "start rollback"
            # State must be cleared so a subsequent rollback isn't locked out.
            assert mod._UPDATE_STATE["running"] is False
        finally:
            mod._set_update_state(False, None)


class TestUpdateStatusIncludesPrevVersion:
    """/settings/update_status surfaces prev_version for UI button gating."""

    def test_update_status_includes_prev_version_when_present(
        self, client, monkeypatch, tmp_path
    ):
        import blueprints.settings as mod

        monkeypatch.setenv("INKYPI_LOCKFILE_DIR", str(tmp_path))
        _write_prev_version(tmp_path, "v0.52.0")
        mod._set_update_state(False, None)

        resp = client.get("/settings/update_status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["prev_version"] == "v0.52.0"

    def test_update_status_prev_version_null_when_missing(
        self, client, monkeypatch, tmp_path
    ):
        import blueprints.settings as mod

        monkeypatch.setenv("INKYPI_LOCKFILE_DIR", str(tmp_path))
        mod._set_update_state(False, None)

        resp = client.get("/settings/update_status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "prev_version" in data
        assert data["prev_version"] is None

    def test_update_status_prev_version_null_when_malformed(
        self, client, monkeypatch, tmp_path
    ):
        """Corrupt prev_version (fails semver) is surfaced as null."""
        import blueprints.settings as mod

        monkeypatch.setenv("INKYPI_LOCKFILE_DIR", str(tmp_path))
        _write_prev_version(tmp_path, "not-a-version")
        mod._set_update_state(False, None)

        resp = client.get("/settings/update_status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["prev_version"] is None
