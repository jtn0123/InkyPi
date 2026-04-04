# pyright: reportMissingImports=false
"""Tests for settings blueprint — logs, health, misc routes, and helpers."""

import time
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# /settings/client_log (POST) - client error logging
# ---------------------------------------------------------------------------


class TestClientLog:
    def test_client_log_info(self, client):
        resp = client.post(
            "/settings/client_log",
            json={
                "level": "info",
                "message": "test log message",
            },
        )
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_client_log_error(self, client):
        resp = client.post(
            "/settings/client_log",
            json={
                "level": "error",
                "message": "something broke",
            },
        )
        assert resp.status_code == 200

    def test_client_log_warning(self, client):
        resp = client.post(
            "/settings/client_log",
            json={
                "level": "warn",
                "message": "warning msg",
            },
        )
        assert resp.status_code == 200

    def test_client_log_debug(self, client):
        resp = client.post(
            "/settings/client_log",
            json={
                "level": "debug",
                "message": "debug msg",
            },
        )
        assert resp.status_code == 200

    def test_client_log_with_extra(self, client):
        resp = client.post(
            "/settings/client_log",
            json={
                "level": "info",
                "message": "with extra",
                "extra": {"key": "value", "count": 42},
            },
        )
        assert resp.status_code == 200

    def test_client_log_invalid_body(self, client):
        resp = client.post(
            "/settings/client_log", data="not json", content_type="application/json"
        )
        assert resp.status_code == 400

    def test_client_log_missing_fields_defaults(self, client):
        """Missing level/message should default gracefully."""
        resp = client.post("/settings/client_log", json={})
        assert resp.status_code == 200

    def test_client_log_unknown_level_defaults_to_info(self, client):
        resp = client.post(
            "/settings/client_log",
            json={
                "level": "trace",
                "message": "unknown level",
            },
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# /shutdown (POST) - shutdown/reboot
# ---------------------------------------------------------------------------


class TestShutdown:
    def test_shutdown_success(self, client, monkeypatch):
        import subprocess

        monkeypatch.setattr(subprocess, "run", MagicMock())
        resp = client.post("/shutdown", json={"reboot": False})
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_reboot_success(self, client, monkeypatch):
        import subprocess

        import blueprints.settings as mod

        mod._shutdown_limiter.reset()
        monkeypatch.setattr(subprocess, "run", MagicMock())
        resp = client.post("/shutdown", json={"reboot": True})
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_shutdown_rate_limited(self, client, monkeypatch):
        import subprocess

        monkeypatch.setattr(subprocess, "run", MagicMock())
        # First call succeeds
        resp1 = client.post("/shutdown", json={})
        assert resp1.status_code == 200
        # Second call within cooldown should be rate limited
        resp2 = client.post("/shutdown", json={})
        assert resp2.status_code == 429

    def test_shutdown_command_failure(self, client, monkeypatch):
        import subprocess

        import blueprints.settings as mod

        mod._shutdown_limiter.reset()
        monkeypatch.setattr(
            subprocess,
            "run",
            MagicMock(side_effect=subprocess.CalledProcessError(1, "sudo")),
        )
        resp = client.post("/shutdown", json={})
        assert resp.status_code == 500

    def test_shutdown_no_json_body(self, client, monkeypatch):
        """POST /shutdown with no body should default to shutdown (not reboot)."""
        import subprocess

        import blueprints.settings as mod

        mod._shutdown_limiter.reset()
        mock_run = MagicMock()
        monkeypatch.setattr(subprocess, "run", mock_run)
        resp = client.post("/shutdown")
        assert resp.status_code == 200
        # Should have called shutdown, not reboot
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "shutdown" in args


# ---------------------------------------------------------------------------
# /api/logs (GET) - log retrieval
# ---------------------------------------------------------------------------


class TestApiLogs:
    def test_api_logs_default(self, client):
        resp = client.get("/api/logs")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "lines" in data
        assert "count" in data
        assert "meta" in data

    def test_api_logs_with_hours(self, client):
        resp = client.get("/api/logs?hours=1")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["meta"]["hours"] == 1

    def test_api_logs_hours_clamped_high(self, client):
        resp = client.get("/api/logs?hours=999")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["meta"]["hours"] <= 24

    def test_api_logs_hours_clamped_low(self, client):
        resp = client.get("/api/logs?hours=0")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["meta"]["hours"] >= 1

    def test_api_logs_with_limit(self, client):
        resp = client.get("/api/logs?limit=100")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["meta"]["limit"] == 100

    def test_api_logs_with_contains(self, client):
        resp = client.get("/api/logs?contains=test")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["meta"]["contains"] == "test"

    def test_api_logs_contains_trimmed(self, client):
        """Contains filter >200 chars should be trimmed."""
        long_filter = "x" * 250
        resp = client.get(f"/api/logs?contains={long_filter}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["meta"]["contains"]) == 200
        assert data["truncated"] is True

    def test_api_logs_level_errors(self, client):
        resp = client.get("/api/logs?level=errors")
        assert resp.status_code == 200

    def test_api_logs_level_warnings(self, client):
        resp = client.get("/api/logs?level=warnings")
        assert resp.status_code == 200

    def test_api_logs_invalid_hours(self, client):
        resp = client.get("/api/logs?hours=abc")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["meta"]["hours"] == 2  # default

    def test_api_logs_rate_limited(self, client, monkeypatch):
        import blueprints.settings as mod

        monkeypatch.setattr(mod, "_rate_limit_ok", lambda addr: False)
        resp = client.get("/api/logs")
        assert resp.status_code == 429

    def test_api_logs_with_update_unit(self, client, monkeypatch):
        """When an update is running, logs should include the update unit."""
        import blueprints.settings as mod

        mod._set_update_state(True, "inkypi-update-test.service")
        try:
            resp = client.get("/api/logs")
            assert resp.status_code == 200
            data = resp.get_json()
            assert "inkypi-update-test.service" in data["meta"]["units"]
        finally:
            mod._set_update_state(False, None)


# ---------------------------------------------------------------------------
# /download-logs (GET) - download logs
# ---------------------------------------------------------------------------


class TestDownloadLogs:
    def test_download_logs_default(self, client):
        resp = client.get("/download-logs")
        assert resp.status_code == 200
        assert resp.content_type == "text/plain; charset=utf-8"
        assert "attachment" in resp.headers.get("Content-Disposition", "")

    def test_download_logs_custom_hours(self, client):
        resp = client.get("/download-logs?hours=4")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Benchmark API endpoints
# ---------------------------------------------------------------------------


class TestBenchmarkAPIs:
    def test_benchmarks_summary_disabled(self, client, monkeypatch):
        import blueprints.settings as mod

        monkeypatch.setattr(mod, "_benchmarks_enabled", lambda: False)
        resp = client.get("/api/benchmarks/summary")
        assert resp.status_code == 404

    def test_benchmarks_summary_enabled(self, client, monkeypatch, tmp_path):
        import blueprints.settings as mod

        monkeypatch.setattr(mod, "_benchmarks_enabled", lambda: True)
        db_path = str(tmp_path / "bench.db")
        monkeypatch.setattr(mod, "_get_bench_db_path", lambda: db_path)
        resp = client.get("/api/benchmarks/summary")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["count"] == 0

    def test_benchmarks_refreshes_disabled(self, client, monkeypatch):
        import blueprints.settings as mod

        monkeypatch.setattr(mod, "_benchmarks_enabled", lambda: False)
        resp = client.get("/api/benchmarks/refreshes")
        assert resp.status_code == 404

    def test_benchmarks_refreshes_enabled(self, client, monkeypatch, tmp_path):
        import blueprints.settings as mod

        monkeypatch.setattr(mod, "_benchmarks_enabled", lambda: True)
        db_path = str(tmp_path / "bench.db")
        monkeypatch.setattr(mod, "_get_bench_db_path", lambda: db_path)
        resp = client.get("/api/benchmarks/refreshes")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_benchmarks_plugins_disabled(self, client, monkeypatch):
        import blueprints.settings as mod

        monkeypatch.setattr(mod, "_benchmarks_enabled", lambda: False)
        resp = client.get("/api/benchmarks/plugins")
        assert resp.status_code == 404

    def test_benchmarks_plugins_enabled(self, client, monkeypatch, tmp_path):
        import blueprints.settings as mod

        monkeypatch.setattr(mod, "_benchmarks_enabled", lambda: True)
        db_path = str(tmp_path / "bench.db")
        monkeypatch.setattr(mod, "_get_bench_db_path", lambda: db_path)
        resp = client.get("/api/benchmarks/plugins")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_benchmarks_stages_no_refresh_id(self, client, monkeypatch):
        import blueprints.settings as mod

        monkeypatch.setattr(mod, "_benchmarks_enabled", lambda: True)
        resp = client.get("/api/benchmarks/stages")
        assert resp.status_code == 422

    def test_benchmarks_stages_with_refresh_id(self, client, monkeypatch, tmp_path):
        import blueprints.settings as mod

        monkeypatch.setattr(mod, "_benchmarks_enabled", lambda: True)
        db_path = str(tmp_path / "bench.db")
        monkeypatch.setattr(mod, "_get_bench_db_path", lambda: db_path)
        resp = client.get("/api/benchmarks/stages?refresh_id=abc-123")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_benchmarks_stages_disabled(self, client, monkeypatch):
        import blueprints.settings as mod

        monkeypatch.setattr(mod, "_benchmarks_enabled", lambda: False)
        resp = client.get("/api/benchmarks/stages?refresh_id=abc")
        assert resp.status_code == 404

    def test_benchmarks_summary_with_window(self, client, monkeypatch, tmp_path):
        import blueprints.settings as mod

        monkeypatch.setattr(mod, "_benchmarks_enabled", lambda: True)
        db_path = str(tmp_path / "bench.db")
        monkeypatch.setattr(mod, "_get_bench_db_path", lambda: db_path)
        resp = client.get("/api/benchmarks/summary?window=1h")
        assert resp.status_code == 200

    def test_benchmarks_refreshes_with_cursor(self, client, monkeypatch, tmp_path):
        import blueprints.settings as mod

        monkeypatch.setattr(mod, "_benchmarks_enabled", lambda: True)
        db_path = str(tmp_path / "bench.db")
        monkeypatch.setattr(mod, "_get_bench_db_path", lambda: db_path)
        resp = client.get("/api/benchmarks/refreshes?cursor=999")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Health API endpoints
# ---------------------------------------------------------------------------


class TestHealthAPIs:
    def test_health_plugins(self, client):
        resp = client.get("/api/health/plugins")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_health_system(self, client):
        resp = client.get("/api/health/system")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_health_system_no_psutil(self, client, monkeypatch):
        """When psutil is unavailable, system health returns None fields."""
        import blueprints.settings as mod

        _original = mod.health_system  # noqa: F841 — kept for potential future use

        # Patch psutil import to fail within the route
        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "psutil":
                raise ImportError("no psutil")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        resp = client.get("/api/health/system")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True


# ---------------------------------------------------------------------------
# /settings and /settings/backup pages
# ---------------------------------------------------------------------------


class TestSettingsPages:
    def test_settings_page(self, client):
        resp = client.get("/settings")
        assert resp.status_code == 200

    def test_backup_restore_page(self, client):
        resp = client.get("/settings/backup")
        assert resp.status_code == 200

    def test_api_keys_page(self, client):
        resp = client.get("/settings/api-keys")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Helper function unit tests
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_window_since_seconds_hours(self):
        from blueprints.settings import _window_since_seconds

        result = _window_since_seconds("6h")
        assert result > 0
        assert result < time.time()

    def test_window_since_seconds_minutes(self):
        from blueprints.settings import _window_since_seconds

        result = _window_since_seconds("30m")
        assert result > 0

    def test_window_since_seconds_days(self):
        from blueprints.settings import _window_since_seconds

        result = _window_since_seconds("2d")
        assert result > 0

    def test_window_since_seconds_none(self):
        from blueprints.settings import _window_since_seconds

        result = _window_since_seconds(None)
        # Should default to 24h ago
        assert abs(result - (time.time() - 24 * 3600)) < 2

    def test_window_since_seconds_invalid_defaults_to_24h(self):
        from blueprints.settings import _window_since_seconds

        result = _window_since_seconds("abch")
        assert abs(result - (time.time() - 24 * 3600)) < 2

    def test_window_since_seconds_invalid_does_not_log_raw_input(self):
        from blueprints.settings import _window_since_seconds

        raw_window = "not-a-number\nforged-log-lineh"
        logger = _window_since_seconds.__globals__["logger"]
        with patch.object(logger, "warning") as warning_mock:
            _window_since_seconds(raw_window)

        warning_mock.assert_called_once_with(
            "Invalid benchmark window provided, defaulting to 24h"
        )

    def test_pct_empty(self):
        from blueprints.settings import _pct

        assert _pct([], 0.5) is None

    def test_pct_values(self):
        from blueprints.settings import _pct

        assert _pct([10, 20, 30, 40, 50], 0.5) == 30

    def test_clamp_int(self):
        from blueprints.settings import _clamp_int

        assert _clamp_int("5", 10, 1, 100) == 5
        assert _clamp_int("200", 10, 1, 100) == 100
        assert _clamp_int("0", 10, 1, 100) == 1
        assert _clamp_int(None, 10, 1, 100) == 10
        assert _clamp_int("abc", 10, 1, 100) == 10

    def test_rate_limit_ok(self):
        from blueprints.settings import _logs_limiter, _rate_limit_ok

        _logs_limiter._requests.clear()
        assert _rate_limit_ok("127.0.0.1") is True

    def test_benchmarks_enabled_default(self, monkeypatch):
        monkeypatch.delenv("INKYPI_BENCHMARK_API_ENABLED", raising=False)
        from blueprints.settings import _benchmarks_enabled

        assert _benchmarks_enabled() is True

    def test_benchmarks_disabled(self, monkeypatch):
        monkeypatch.setenv("INKYPI_BENCHMARK_API_ENABLED", "false")
        from blueprints.settings import _benchmarks_enabled

        assert _benchmarks_enabled() is False
