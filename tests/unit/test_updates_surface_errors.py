# pyright: reportMissingImports=false
"""Tests for JTN-710: surface update failures in the web UI.

Covers two sides of the fix:

1. ``/settings/update_status`` now includes ``last_failure`` read from
   ``/var/lib/inkypi/.last-update-failure`` (the file written by the EXIT
   trap in ``install/update.sh``, JTN-704).
2. ``POST /settings/update`` now rejects null/empty ``target_version`` with
   a ``validation_error`` envelope instead of silently falling through to
   the "latest semver tag" code path.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock


class TestUpdateStatusLastFailure:
    """GET /settings/update_status surfaces .last-update-failure contents."""

    def test_update_status_includes_last_failure_when_file_present(
        self, client, monkeypatch, tmp_path
    ):
        import blueprints.settings as mod

        mod._set_update_state(False, None)
        failure_payload = {
            "timestamp": "2026-04-14T23:00:00Z",
            "exit_code": 97,
            "last_command": "apt_install",
            "recent_journal_lines": "apt-get: failed\nE: could not resolve",
        }
        (tmp_path / ".last-update-failure").write_text(
            json.dumps(failure_payload), encoding="utf-8"
        )
        monkeypatch.setenv("INKYPI_LOCKFILE_DIR", str(tmp_path))

        resp = client.get("/settings/update_status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["last_failure"] == failure_payload

    def test_update_status_last_failure_null_when_missing(
        self, client, monkeypatch, tmp_path
    ):
        import blueprints.settings as mod

        mod._set_update_state(False, None)
        # tmp_path exists but contains no .last-update-failure file
        monkeypatch.setenv("INKYPI_LOCKFILE_DIR", str(tmp_path))

        resp = client.get("/settings/update_status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "last_failure" in data
        assert data["last_failure"] is None

    def test_update_status_handles_malformed_failure_json(
        self, client, monkeypatch, tmp_path
    ):
        """Malformed JSON must not crash the endpoint."""
        import blueprints.settings as mod

        mod._set_update_state(False, None)
        (tmp_path / ".last-update-failure").write_text(
            "{ this is not json",
            encoding="utf-8",
        )
        monkeypatch.setenv("INKYPI_LOCKFILE_DIR", str(tmp_path))

        resp = client.get("/settings/update_status")
        assert resp.status_code == 200
        data = resp.get_json()
        # Helper returns {"parse_error": True} for unreadable/malformed records
        assert data["last_failure"] == {"parse_error": True}

    def test_update_status_handles_non_object_failure_json(
        self, client, monkeypatch, tmp_path
    ):
        """A JSON array/scalar at the top level is still treated as parse_error."""
        import blueprints.settings as mod

        mod._set_update_state(False, None)
        (tmp_path / ".last-update-failure").write_text("[1, 2, 3]", encoding="utf-8")
        monkeypatch.setenv("INKYPI_LOCKFILE_DIR", str(tmp_path))

        resp = client.get("/settings/update_status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["last_failure"] == {"parse_error": True}


class TestSynthesizeFailureFromJournal:
    """JTN-787: when the transient systemd unit is ``failed`` but no
    ``.last-update-failure`` file exists, synthesize one from the unit's
    journal tail so the UI still has *something* to show. This covers the
    case where ``install/do_update.sh`` on a pre-JTN-787 install aborts
    before delegating to ``install/update.sh``."""

    def test_synthesizes_last_failure_when_unit_failed_and_no_file(
        self, client, monkeypatch, tmp_path
    ):
        import subprocess as real_subprocess

        import blueprints.settings as mod

        # Mark an update as running with a known unit so the auto-clear
        # path is reached.
        mod._UPDATE_STATE["running"] = True
        mod._UPDATE_STATE["unit"] = "inkypi-update-1234.service"
        mod._UPDATE_STATE["started_at"] = 1_000_000.0

        # Isolate lockfile dir so the real ``.last-update-failure`` (if any)
        # on the developer box doesn't leak in.
        monkeypatch.setenv("INKYPI_LOCKFILE_DIR", str(tmp_path))
        monkeypatch.setattr(mod, "_systemd_available", lambda: True)

        journal_output = (
            "Apr 20 12:00:00 host do_update.sh[1234]: error: Your local "
            "changes to the following files would be overwritten by "
            "checkout:\n"
            "    src/static/styles/main.css\n"
            "Please commit your changes or stash them before you switch "
            "branches.\nAborting\n"
        )

        def fake_run(cmd, *args, **kwargs):
            # systemctl is-active -> "failed"
            if cmd[:2] == ["systemctl", "is-active"]:
                return real_subprocess.CompletedProcess(
                    args=cmd, returncode=0, stdout="failed\n", stderr=""
                )
            # journalctl -u <unit> -n 20 --no-pager -> the tail
            if cmd[:2] == ["journalctl", "-u"]:
                return real_subprocess.CompletedProcess(
                    args=cmd, returncode=0, stdout=journal_output, stderr=""
                )
            return real_subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="", stderr=""
            )

        # subprocess is imported lazily inside update_status; patch the
        # module-level ``subprocess.run`` directly (the view's
        # ``import subprocess`` returns the same cached module object).
        monkeypatch.setattr("subprocess.run", fake_run)

        try:
            resp = client.get("/settings/update_status")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["running"] is False  # auto-cleared
            assert data["last_failure"] is not None
            lf = data["last_failure"]
            assert lf.get("synthesized") is True
            assert lf.get("last_command") == "systemd_unit_failed"
            assert "main.css" in lf.get("recent_journal_lines", "")
            assert lf.get("unit") == "inkypi-update-1234.service"
        finally:
            mod._set_update_state(False, None)

    def test_does_not_synthesize_when_failure_file_already_exists(
        self, client, monkeypatch, tmp_path
    ):
        """If update.sh already wrote .last-update-failure, that record wins
        and we must not overwrite it with the journal-synthesized one."""
        import subprocess as real_subprocess

        import blueprints.settings as mod

        real_failure = {
            "timestamp": "2026-04-20T00:00:00Z",
            "exit_code": 97,
            "last_command": "pip_requirements",
            "recent_journal_lines": "real failure record",
        }
        (tmp_path / ".last-update-failure").write_text(
            json.dumps(real_failure), encoding="utf-8"
        )
        monkeypatch.setenv("INKYPI_LOCKFILE_DIR", str(tmp_path))

        mod._UPDATE_STATE["running"] = True
        mod._UPDATE_STATE["unit"] = "inkypi-update-5678.service"
        mod._UPDATE_STATE["started_at"] = 1_000_000.0
        monkeypatch.setattr(mod, "_systemd_available", lambda: True)

        def fake_run(cmd, *args, **kwargs):
            if cmd[:2] == ["systemctl", "is-active"]:
                return real_subprocess.CompletedProcess(
                    args=cmd, returncode=0, stdout="failed\n", stderr=""
                )
            if cmd[:2] == ["journalctl", "-u"]:
                # Should NOT be called; if it is, return a sentinel the
                # assertion below would catch.
                return real_subprocess.CompletedProcess(
                    args=cmd, returncode=0, stdout="SHOULD_NOT_APPEAR", stderr=""
                )
            return real_subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="", stderr=""
            )

        monkeypatch.setattr("subprocess.run", fake_run)

        try:
            resp = client.get("/settings/update_status")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["last_failure"] == real_failure
            assert "synthesized" not in data["last_failure"]
        finally:
            mod._set_update_state(False, None)


class TestStartUpdateRejectsEmptyTargetVersion:
    """POST /settings/update validates ``target_version`` explicitly."""

    def _install_mocks(self, monkeypatch):
        import blueprints.settings as mod

        monkeypatch.setattr(mod, "_systemd_available", lambda: False)
        monkeypatch.setattr(mod, "_get_update_script_path", lambda: None)
        fallback_mock = MagicMock()
        monkeypatch.setattr(mod, "_start_update_fallback_thread", fallback_mock)
        mod._set_update_state(False, None)
        return mod, fallback_mock

    def test_update_endpoint_rejects_null_target_version_with_validation_error(
        self, client, monkeypatch
    ):
        mod, fallback_mock = self._install_mocks(monkeypatch)
        try:
            resp = client.post("/settings/update", json={"target_version": None})
            assert resp.status_code == 400
            data = resp.get_json()
            assert data["success"] is False
            assert data["code"] == "validation_error"
            assert data["details"] == {"field": "target_version"}
            fallback_mock.assert_not_called()
        finally:
            mod._set_update_state(False, None)

    def test_update_endpoint_rejects_empty_target_version_with_validation_error(
        self, client, monkeypatch
    ):
        mod, fallback_mock = self._install_mocks(monkeypatch)
        try:
            resp = client.post("/settings/update", json={"target_version": ""})
            assert resp.status_code == 400
            data = resp.get_json()
            assert data["success"] is False
            assert data["code"] == "validation_error"
            assert data["details"] == {"field": "target_version"}
            fallback_mock.assert_not_called()
        finally:
            mod._set_update_state(False, None)

    def test_update_endpoint_rejects_whitespace_only_target_version(
        self, client, monkeypatch
    ):
        mod, fallback_mock = self._install_mocks(monkeypatch)
        try:
            resp = client.post("/settings/update", json={"target_version": "   "})
            assert resp.status_code == 400
            data = resp.get_json()
            assert data["code"] == "validation_error"
            assert data["details"] == {"field": "target_version"}
            fallback_mock.assert_not_called()
        finally:
            mod._set_update_state(False, None)

    def test_update_endpoint_rejects_non_string_target_version(
        self, client, monkeypatch
    ):
        mod, fallback_mock = self._install_mocks(monkeypatch)
        try:
            resp = client.post("/settings/update", json={"target_version": 123})
            assert resp.status_code == 400
            data = resp.get_json()
            assert data["code"] == "validation_error"
            assert data["details"] == {"field": "target_version"}
            fallback_mock.assert_not_called()
        finally:
            mod._set_update_state(False, None)

    def test_update_endpoint_invalid_tag_format_returns_validation_envelope(
        self, client, monkeypatch
    ):
        """Existing invalid-format rejection now also uses the envelope."""
        mod, fallback_mock = self._install_mocks(monkeypatch)
        try:
            resp = client.post(
                "/settings/update", json={"target_version": "not-a-version"}
            )
            assert resp.status_code == 400
            data = resp.get_json()
            assert data["code"] == "validation_error"
            assert data["details"] == {"field": "target_version"}
            fallback_mock.assert_not_called()
        finally:
            mod._set_update_state(False, None)

    def test_update_endpoint_missing_target_version_still_allowed(
        self, client, monkeypatch
    ):
        """Omitting ``target_version`` entirely remains valid (latest-tag path)."""
        mod, fallback_mock = self._install_mocks(monkeypatch)
        try:
            resp = client.post("/settings/update", json={})
            assert resp.status_code == 200
            fallback_mock.assert_called_once_with(None, target_tag=None)
        finally:
            mod._set_update_state(False, None)


class TestReadLastUpdateFailureHelper:
    """Direct unit tests for the read_last_update_failure helper."""

    def test_returns_none_when_file_missing(self, monkeypatch, tmp_path):
        from blueprints.settings._update_status import read_last_update_failure

        monkeypatch.setenv("INKYPI_LOCKFILE_DIR", str(tmp_path))
        assert read_last_update_failure() is None

    def test_returns_parsed_record_when_present(self, monkeypatch, tmp_path):
        from blueprints.settings._update_status import read_last_update_failure

        record = {
            "timestamp": "2026-04-14T00:00:00Z",
            "exit_code": 1,
            "last_command": "stop_service",
            "recent_journal_lines": "line1\nline2",
        }
        (tmp_path / ".last-update-failure").write_text(
            json.dumps(record), encoding="utf-8"
        )
        monkeypatch.setenv("INKYPI_LOCKFILE_DIR", str(tmp_path))
        assert read_last_update_failure() == record

    def test_caps_oversized_file(self, monkeypatch, tmp_path):
        """A 1 MiB failure file must not blow up the response."""
        from blueprints.settings._update_status import read_last_update_failure

        (tmp_path / ".last-update-failure").write_text(
            "x" * (1024 * 1024), encoding="utf-8"
        )
        monkeypatch.setenv("INKYPI_LOCKFILE_DIR", str(tmp_path))
        # Oversized + unparseable content yields the parse_error sentinel.
        assert read_last_update_failure() == {"parse_error": True}
