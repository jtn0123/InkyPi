"""Tests for utils/refresh_stats.py and GET /api/stats.

Covers:
  - success_rate calculation
  - P50/P95 from a known distribution
  - top_failing aggregation
  - in-process cache: same call within 60 s returns same dict object
  - GET /api/stats returns 200 with the correct shape
"""

from __future__ import annotations

import json
import time

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_sidecar(directory, filename, **kwargs):
    """Write a JSON sidecar file with the given fields into *directory*."""
    path = directory / filename
    path.write_text(json.dumps(kwargs), encoding="utf-8")
    return path


def _make_sidecars(tmp_path, records):
    """Write a list of sidecar dicts (with auto-generated names) and return the dir."""
    for i, rec in enumerate(records):
        _write_sidecar(tmp_path, f"display_{i:04d}.json", **rec)
    return str(tmp_path)


# ---------------------------------------------------------------------------
# Unit tests for compute_stats
# ---------------------------------------------------------------------------


class TestComputeStats:
    def setup_method(self):
        # Always start each test with a clean cache
        from utils.refresh_stats import _clear_cache

        _clear_cache()

    def _now_ts(self):
        return time.time()

    def test_empty_directory(self, tmp_path):
        from utils.refresh_stats import compute_stats

        result = compute_stats(str(tmp_path), 3600)
        assert result["total"] == 0
        assert result["success"] == 0
        assert result["failure"] == 0
        assert result["success_rate"] == 0.0
        assert result["p50_duration_ms"] == 0
        assert result["p95_duration_ms"] == 0
        assert result["top_failing"] == []

    def test_success_rate_calculation(self, tmp_path):
        from utils.refresh_stats import compute_stats

        now = self._now_ts()
        records = [
            {"status": "success", "duration_ms": 100, "timestamp": now - 10},
            {"status": "success", "duration_ms": 200, "timestamp": now - 20},
            {
                "status": "failure",
                "duration_ms": 50,
                "plugin_id": "clock",
                "timestamp": now - 30,
            },
            {
                "status": "failure",
                "duration_ms": 75,
                "plugin_id": "weather",
                "timestamp": now - 40,
            },
        ]
        hist_dir = _make_sidecars(tmp_path, records)
        result = compute_stats(hist_dir, 3600)

        assert result["total"] == 4
        assert result["success"] == 2
        assert result["failure"] == 2
        assert result["success_rate"] == pytest.approx(0.5, abs=1e-4)

    def test_all_success(self, tmp_path):
        from utils.refresh_stats import compute_stats

        now = self._now_ts()
        records = [
            {"status": "success", "duration_ms": 100, "timestamp": now - 5},
            {"status": "success", "duration_ms": 150, "timestamp": now - 10},
        ]
        hist_dir = _make_sidecars(tmp_path, records)
        result = compute_stats(hist_dir, 3600)
        assert result["success_rate"] == 1.0
        assert result["failure"] == 0
        assert result["top_failing"] == []

    def test_p50_p95_known_distribution(self, tmp_path):
        from utils.refresh_stats import compute_stats

        now = self._now_ts()
        # 10 values: 100, 200, 300, ... 1000 ms (sorted)
        records = [
            {"status": "success", "duration_ms": (i + 1) * 100, "timestamp": now - i}
            for i in range(10)
        ]
        hist_dir = _make_sidecars(tmp_path, records)
        result = compute_stats(hist_dir, 3600)

        assert result["total"] == 10
        # P50 index = int(10 * 50 / 100) = 5 → value at index 5 = 600
        assert result["p50_duration_ms"] == 600
        # P95 index = int(10 * 95 / 100) = 9 → value at index 9 = 1000
        assert result["p95_duration_ms"] == 1000

    def test_top_failing_aggregation(self, tmp_path):
        from utils.refresh_stats import compute_stats

        now = self._now_ts()
        records = [
            {"status": "failure", "plugin_id": "clock", "timestamp": now - 1},
            {"status": "failure", "plugin_id": "clock", "timestamp": now - 2},
            {"status": "failure", "plugin_id": "clock", "timestamp": now - 3},
            {"status": "failure", "plugin_id": "weather", "timestamp": now - 4},
            {"status": "failure", "plugin_id": "weather", "timestamp": now - 5},
            {"status": "failure", "plugin_id": "nasa", "timestamp": now - 6},
            {"status": "success", "plugin_id": "clock", "timestamp": now - 7},
        ]
        hist_dir = _make_sidecars(tmp_path, records)
        result = compute_stats(hist_dir, 3600)

        top = result["top_failing"]
        assert len(top) >= 1
        # clock should be first (3 failures)
        assert top[0]["plugin"] == "clock"
        assert top[0]["count"] == 3
        # weather is second (2 failures)
        assert top[1]["plugin"] == "weather"
        assert top[1]["count"] == 2
        # nasa is third (1 failure)
        assert top[2]["plugin"] == "nasa"
        assert top[2]["count"] == 1

    def test_window_filters_old_records(self, tmp_path):
        from utils.refresh_stats import compute_stats

        now = self._now_ts()
        records = [
            # inside 1h window
            {"status": "success", "duration_ms": 100, "timestamp": now - 1800},
            # outside 1h but inside 24h
            {
                "status": "failure",
                "plugin_id": "clock",
                "duration_ms": 200,
                "timestamp": now - 7200,
            },
        ]
        hist_dir = _make_sidecars(tmp_path, records)

        result_1h = compute_stats(hist_dir, 3600)
        assert result_1h["total"] == 1
        assert result_1h["success"] == 1

        from utils.refresh_stats import _clear_cache

        _clear_cache()

        result_24h = compute_stats(hist_dir, 86400)
        assert result_24h["total"] == 2
        assert result_24h["failure"] == 1

    def test_cache_returns_same_dict_within_60s(self, tmp_path, monkeypatch):
        """Same call within 60 s returns the cached dict without re-reading files."""
        import utils.refresh_stats as rs

        now_val = time.time()
        call_count = 0

        original_load = rs._load_sidecars

        def counting_load(hdir, since):
            nonlocal call_count
            call_count += 1
            return original_load(hdir, since)

        monkeypatch.setattr(rs, "_load_sidecars", counting_load)

        # Freeze time so the second call is within the TTL
        monkeypatch.setattr(rs, "_now", lambda: now_val)

        hist_dir = str(tmp_path)
        result_first = rs.compute_stats(hist_dir, 3600)
        result_second = rs.compute_stats(hist_dir, 3600)

        assert call_count == 1, "second call within TTL should hit cache"
        assert result_first is result_second

    def test_cache_expires_after_ttl(self, tmp_path, monkeypatch):
        """After the TTL, the next call re-reads the directory."""
        import utils.refresh_stats as rs

        call_count = 0

        original_load = rs._load_sidecars

        def counting_load(hdir, since):
            nonlocal call_count
            call_count += 1
            return original_load(hdir, since)

        monkeypatch.setattr(rs, "_load_sidecars", counting_load)

        start = time.time()
        monkeypatch.setattr(rs, "_now", lambda: start)
        rs.compute_stats(str(tmp_path), 3600)

        # Advance time past the TTL
        monkeypatch.setattr(rs, "_now", lambda: start + rs._CACHE_TTL_SECONDS + 1)
        rs.compute_stats(str(tmp_path), 3600)

        assert call_count == 2, "cache should expire after TTL"

    def test_missing_duration_skipped_in_percentiles(self, tmp_path):
        from utils.refresh_stats import compute_stats

        now = self._now_ts()
        records = [
            # no duration_ms field
            {"status": "success", "timestamp": now - 1},
            {"status": "success", "duration_ms": 500, "timestamp": now - 2},
        ]
        hist_dir = _make_sidecars(tmp_path, records)
        result = compute_stats(hist_dir, 3600)
        assert result["total"] == 2
        # Only one duration contributed; p50 should be 500
        assert result["p50_duration_ms"] == 500

    def test_unknown_plugin_id_on_failure(self, tmp_path):
        from utils.refresh_stats import compute_stats

        now = self._now_ts()
        records = [
            {"status": "failure", "timestamp": now - 1},  # no plugin_id
        ]
        hist_dir = _make_sidecars(tmp_path, records)
        result = compute_stats(hist_dir, 3600)
        assert result["top_failing"][0]["plugin"] == "unknown"

    def test_nonexistent_directory(self):
        from utils.refresh_stats import compute_stats

        result = compute_stats("/nonexistent/path/xyz123", 3600)
        assert result["total"] == 0


# ---------------------------------------------------------------------------
# Integration test via Flask test client
# ---------------------------------------------------------------------------


class TestApiStatsEndpoint:
    """Tests for GET /api/stats via the Flask test client."""

    def test_returns_200_with_correct_shape(self, client):
        resp = client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data is not None
        for window in ("last_1h", "last_24h", "last_7d"):
            assert window in data, f"missing window {window!r}"
            w = data[window]
            for key in (
                "total",
                "success",
                "failure",
                "success_rate",
                "p50_duration_ms",
                "p95_duration_ms",
                "top_failing",
            ):
                assert key in w, f"{window} missing key {key!r}"
            assert isinstance(w["top_failing"], list)
            assert 0.0 <= w["success_rate"] <= 1.0

    def test_cache_control_header(self, client):
        resp = client.get("/api/stats")
        assert resp.status_code == 200
        cc = resp.headers.get("Cache-Control", "")
        assert "max-age=60" in cc

    def test_empty_history_returns_zeros(self, client, device_config_dev):
        """When the history dir is empty all totals should be 0."""
        resp = client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["last_1h"]["total"] == 0
