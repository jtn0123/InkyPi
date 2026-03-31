# pyright: reportMissingImports=false
"""Tests for settings health and progress SSE endpoints (_health.py)."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock


class TestHealthPlugins:
    def test_filters_stale_entries(self, client, monkeypatch):
        """Entries with last_seen older than the window are filtered out."""
        monkeypatch.setenv("INKYPI_HEALTH_WINDOW_MIN", "1440")

        stale_time = (datetime.now() - timedelta(days=2)).isoformat()
        snapshot = {"old_plugin": {"last_seen": stale_time, "status": "ok"}}

        rt = MagicMock()
        rt.get_health_snapshot.return_value = snapshot

        with client.application.app_context():
            client.application.config["REFRESH_TASK"] = rt

        resp = client.get("/api/health/plugins")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "old_plugin" not in data["items"]

    def test_keeps_recent_entries(self, client, monkeypatch):
        """Entries with recent last_seen are preserved."""
        monkeypatch.setenv("INKYPI_HEALTH_WINDOW_MIN", "1440")
        recent_time = datetime.now().isoformat()
        snapshot = {"fresh_plugin": {"last_seen": recent_time, "status": "ok"}}

        rt = MagicMock()
        rt.get_health_snapshot.return_value = snapshot

        with client.application.app_context():
            client.application.config["REFRESH_TASK"] = rt

        resp = client.get("/api/health/plugins")
        data = resp.get_json()
        assert "fresh_plugin" in data["items"]

    def test_keeps_entries_without_last_seen(self, client, monkeypatch):
        """Entries missing last_seen key are preserved."""
        snapshot = {"no_ts_plugin": {"status": "ok"}}

        rt = MagicMock()
        rt.get_health_snapshot.return_value = snapshot

        with client.application.app_context():
            client.application.config["REFRESH_TASK"] = rt

        resp = client.get("/api/health/plugins")
        data = resp.get_json()
        assert "no_ts_plugin" in data["items"]

    def test_invalid_datetime_preserved(self, client, monkeypatch):
        """Entries with unparseable last_seen are preserved (except path)."""
        snapshot = {"bad_ts": {"last_seen": "not-a-date", "status": "ok"}}

        rt = MagicMock()
        rt.get_health_snapshot.return_value = snapshot

        with client.application.app_context():
            client.application.config["REFRESH_TASK"] = rt

        resp = client.get("/api/health/plugins")
        data = resp.get_json()
        assert "bad_ts" in data["items"]

    def test_window_env_non_numeric(self, client, monkeypatch):
        """Non-numeric INKYPI_HEALTH_WINDOW_MIN falls back to 1440."""
        monkeypatch.setenv("INKYPI_HEALTH_WINDOW_MIN", "abc")

        recent_time = datetime.now().isoformat()
        snapshot = {"plugin": {"last_seen": recent_time}}

        rt = MagicMock()
        rt.get_health_snapshot.return_value = snapshot

        with client.application.app_context():
            client.application.config["REFRESH_TASK"] = rt

        resp = client.get("/api/health/plugins")
        data = resp.get_json()
        assert data["success"] is True
        assert "plugin" in data["items"]

    def test_no_snapshot_method(self, client, monkeypatch):
        """RefreshTask without get_health_snapshot returns empty dict."""
        rt = MagicMock(spec=[])  # no methods at all

        with client.application.app_context():
            client.application.config["REFRESH_TASK"] = rt

        resp = client.get("/api/health/plugins")
        data = resp.get_json()
        assert data["success"] is True
        assert data["items"] == {}

    def test_exception_returns_500(self, client, monkeypatch):
        """Outer exception triggers json_internal_error."""
        # Remove REFRESH_TASK entirely to cause KeyError
        with client.application.app_context():
            client.application.config.pop("REFRESH_TASK", None)

        resp = client.get("/api/health/plugins")
        assert resp.status_code == 500


class TestHealthSystem:
    def test_with_psutil(self, client):
        """Returns numeric system metrics when psutil is available."""
        resp = client.get("/api/health/system")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        # psutil is installed in test env
        assert isinstance(data["cpu_percent"], int | float)
        assert isinstance(data["memory_percent"], int | float)
        assert isinstance(data["disk_percent"], int | float)
        assert isinstance(data["uptime_seconds"], int)

    def test_psutil_unavailable(self, client, monkeypatch):
        """All metrics are None when psutil import fails."""
        import builtins

        real_import = builtins.__import__

        def _block_psutil(name, *args, **kwargs):
            if name == "psutil":
                raise ImportError("blocked")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _block_psutil)

        resp = client.get("/api/health/system")
        data = resp.get_json()
        assert data["success"] is True
        assert data["cpu_percent"] is None
        assert data["memory_percent"] is None
        assert data["disk_percent"] is None
        assert data["uptime_seconds"] is None


class TestProgressStream:
    def test_disabled(self, client, monkeypatch):
        """SSE endpoint returns 404 when disabled."""
        monkeypatch.setenv("INKYPI_PROGRESS_SSE_ENABLED", "false")

        resp = client.get("/api/progress/stream")
        assert resp.status_code == 404

    def test_enabled_mimetype(self, client, monkeypatch):
        """SSE endpoint returns text/event-stream content type."""
        monkeypatch.setenv("INKYPI_PROGRESS_SSE_ENABLED", "true")

        resp = client.get("/api/progress/stream")
        assert resp.status_code == 200
        assert "text/event-stream" in resp.content_type

    def test_last_seq_non_numeric(self, client, monkeypatch):
        """Non-numeric last_seq defaults to 0 without error."""
        monkeypatch.setenv("INKYPI_PROGRESS_SSE_ENABLED", "true")

        resp = client.get("/api/progress/stream?last_seq=abc")
        assert resp.status_code == 200
        assert "text/event-stream" in resp.content_type
