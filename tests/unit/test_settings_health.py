# pyright: reportMissingImports=false
"""Tests for settings health and progress SSE endpoints (_health.py)."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from blueprints.settings import _health


class TestHealthPlugins:
    def test_filters_stale_entries(self, client, monkeypatch):
        """Entries with last_seen older than the window are filtered out."""
        monkeypatch.setenv("INKYPI_HEALTH_WINDOW_MIN", "1440")

        stale_time = (datetime.now(UTC) - timedelta(days=2)).isoformat()
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
        recent_time = datetime.now(UTC).isoformat()
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

        recent_time = datetime.now(UTC).isoformat()
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
        assert isinstance(data["disk_free_gb"], int | float)
        assert isinstance(data["disk_total_gb"], int | float)
        assert isinstance(data["uptime_seconds"], int)

    def test_disk_free_gb_is_plausible(self, client):
        """disk_free_gb must be non-negative and less than or equal to disk_total_gb."""
        resp = client.get("/api/health/system")
        data = resp.get_json()
        assert data["disk_free_gb"] >= 0
        assert data["disk_total_gb"] > 0
        assert data["disk_free_gb"] <= data["disk_total_gb"]

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
        assert data["disk_free_gb"] is None
        assert data["disk_total_gb"] is None
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
        try:
            assert resp.status_code == 200
            assert "text/event-stream" in resp.content_type
        finally:
            resp.close()

    def test_last_seq_non_numeric(self, client, monkeypatch):
        """Non-numeric last_seq defaults to 0 without error."""
        monkeypatch.setenv("INKYPI_PROGRESS_SSE_ENABLED", "true")

        resp = client.get("/api/progress/stream?last_seq=abc")
        try:
            assert resp.status_code == 200
            assert "text/event-stream" in resp.content_type
        finally:
            resp.close()

    def test_connection_cap_returns_503(self, client, monkeypatch):
        """SSE endpoint refuses excess subscribers instead of tying up workers."""
        monkeypatch.setenv("INKYPI_PROGRESS_SSE_ENABLED", "true")
        monkeypatch.setenv("INKYPI_PROGRESS_SSE_MAX_CONNECTIONS", "0")

        resp = client.get("/api/progress/stream")

        assert resp.status_code == 503
        assert resp.get_data(as_text=True) == "Too many progress SSE connections"

    def test_enabled_helper_accepts_truthy_values(self, monkeypatch):
        monkeypatch.setenv("INKYPI_PROGRESS_SSE_ENABLED", "yes")

        assert _health._progress_stream_enabled() is True

    def test_enabled_helper_rejects_disabled_values(self, monkeypatch):
        monkeypatch.setenv("INKYPI_PROGRESS_SSE_ENABLED", "off")

        assert _health._progress_stream_enabled() is False

    def test_iter_progress_events_backfills_and_follows_new_events(self):
        bus = MagicMock()
        bus.recent.return_value = [
            {"seq": 1, "state": "old"},
            {"seq": 3, "state": "ready", "message": "done"},
        ]
        bus.wait_for.return_value = [{"seq": 4, "state": "next"}]

        stream = _health._iter_progress_events(bus, last_seq=2)

        backfill = next(stream)
        assert backfill.startswith("event: ready\n")
        assert '"seq":3' in backfill
        assert '"seq":1' not in backfill
        assert next(stream).startswith("event: next\n")
        bus.wait_for.assert_called_once_with(2, timeout_s=15.0)

    def test_iter_progress_events_emits_keepalive_when_idle(self):
        bus = MagicMock()
        bus.recent.return_value = []
        bus.wait_for.return_value = []

        stream = _health._iter_progress_events(bus, last_seq=0)

        assert next(stream) == ": keep-alive\n\n"
