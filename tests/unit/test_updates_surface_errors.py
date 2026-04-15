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
