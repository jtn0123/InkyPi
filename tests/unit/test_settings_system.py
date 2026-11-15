# pyright: reportMissingImports=false
"""Tests for settings system control endpoints (_system.py)."""

import subprocess
from unittest.mock import MagicMock

import pytest
from flask.testing import FlaskClient


class TestShutdown:
    def test_invalid_json_content_type(
        self, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """application/json with invalid body returns 400."""
        monkeypatch.setattr(subprocess, "run", MagicMock())

        resp = client.post(
            "/shutdown",
            data=b"not json",
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_rate_limit_remaining_seconds(
        self, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """429 error message contains remaining seconds."""

        mock_run = MagicMock()
        monkeypatch.setattr(subprocess, "run", mock_run)

        # First call succeeds
        resp1 = client.post("/shutdown", json={})
        assert resp1.status_code == 200

        # Second call within cooldown → 429
        resp2 = client.post("/shutdown", json={})
        assert resp2.status_code == 429
        data = resp2.get_json()
        assert "wait" in data["error"].lower()
        # Should contain a number of seconds
        import re

        match = re.search(r"\d+", data["error"])
        assert match is not None

    def test_reboot_calls_sudo_reboot(
        self, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Reboot request calls subprocess.run with ['sudo', 'reboot']."""
        mock_run = MagicMock()
        monkeypatch.setattr(subprocess, "run", mock_run)

        resp = client.post("/shutdown", json={"reboot": True})
        assert resp.status_code == 200
        mock_run.assert_called_once_with(["sudo", "reboot"], check=True)

    def test_default_calls_sudo_shutdown(
        self, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Default shutdown calls subprocess.run with ['sudo', 'shutdown', '-h', 'now']."""
        mock_run = MagicMock()
        monkeypatch.setattr(subprocess, "run", mock_run)

        resp = client.post("/shutdown", json={})
        assert resp.status_code == 200
        mock_run.assert_called_once_with(["sudo", "shutdown", "-h", "now"], check=True)

    def test_called_process_error_500(
        self, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CalledProcessError from subprocess returns 500."""
        monkeypatch.setattr(
            subprocess,
            "run",
            MagicMock(side_effect=subprocess.CalledProcessError(1, "sudo shutdown")),
        )

        resp = client.post("/shutdown", json={})
        assert resp.status_code == 500

    def test_no_body_defaults_to_shutdown(
        self, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """POST with no body defaults to shutdown (not reboot)."""
        mock_run = MagicMock()
        monkeypatch.setattr(subprocess, "run", mock_run)

        resp = client.post("/shutdown")
        assert resp.status_code == 200
        mock_run.assert_called_once_with(["sudo", "shutdown", "-h", "now"], check=True)

    def test_empty_dict_defaults_to_shutdown(
        self, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Explicit empty dict body defaults to shutdown."""
        mock_run = MagicMock()
        monkeypatch.setattr(subprocess, "run", mock_run)

        resp = client.post("/shutdown", json={})
        assert resp.status_code == 200
        mock_run.assert_called_once_with(["sudo", "shutdown", "-h", "now"], check=True)
