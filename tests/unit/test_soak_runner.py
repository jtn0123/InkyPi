# pyright: reportMissingImports=false
"""Unit tests for ``scripts/soak_runner.py`` (JTN-733).

These tests exercise the report-shape, duration parsing, and trend summary
logic against canned sampled data. They do NOT hit a live InkyPi instance —
the goal is to lock down the math and report contract that the nightly
workflow artifact will be read against.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "soak_runner.py"


def _load_module():
    """Load ``scripts/soak_runner.py`` as a module regardless of sys.path."""
    spec = importlib.util.spec_from_file_location(
        "soak_runner_under_test", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["soak_runner_under_test"] = module
    spec.loader.exec_module(module)
    return module


soak = _load_module()


# ---------------------------------------------------------------------------
# parse_duration
# ---------------------------------------------------------------------------


class TestParseDuration:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("30s", 30),
            ("30", 30),
            ("10m", 600),
            ("2h", 7200),
            ("1d", 86400),
            ("24h", 86400),
            ("  5m ", 300),
            ("1.5m", 90),
        ],
    )
    def test_valid(self, text, expected):
        assert soak.parse_duration(text) == expected

    @pytest.mark.parametrize("bad", ["", "abc", "5x", "-1m", "0s", None])
    def test_invalid(self, bad):
        with pytest.raises(ValueError):
            soak.parse_duration(bad)


# ---------------------------------------------------------------------------
# parse_diagnostics_payload
# ---------------------------------------------------------------------------


def _payload(**overrides):
    """Canonical /api/diagnostics response, with overrides applied."""
    base = {
        "ts": "2026-04-19T00:00:00+00:00",
        "version": "0.61.7",
        "prev_version": "0.61.6",
        "uptime_s": 3600,
        "memory": {"total_mb": 512, "used_mb": 310, "pct": 60.5},
        "disk": {"total_mb": 16000, "used_mb": 5200, "pct": 32.5, "path": "/"},
        "refresh_task": {
            "running": True,
            "last_run_ts": "2026-04-19T00:00:00+00:00",
            "last_error": None,
        },
        "plugin_health": {
            "clock": "ok",
            "weather": "ok",
            "calendar": "ok",
            "rss": "ok",
            "wpotd": "ok",
        },
        "log_tail_100": [],
        "last_update_failure": None,
        "recent_client_log_errors": {
            "count_5m": 0,
            "warn_count_5m": 0,
            "last_error_ts": None,
            "window_seconds": 300,
        },
    }
    for k, v in overrides.items():
        base[k] = v
    return base


class TestParsePayload:
    def test_happy_path(self):
        s = soak.parse_diagnostics_payload(
            _payload(), elapsed_s=1.0, http_status=200
        )
        assert s.fetch_ok is True
        assert s.fetch_error is None
        assert s.http_status == 200
        assert s.memory_pct == 60.5
        assert s.disk_pct == 32.5
        assert s.uptime_s == 3600
        assert s.version == "0.61.7"
        assert s.refresh_running is True
        assert s.refresh_last_error is None
        assert s.client_log_count_5m == 0
        assert s.plugin_health == {
            "clock": "ok",
            "weather": "ok",
            "calendar": "ok",
            "rss": "ok",
            "wpotd": "ok",
        }

    def test_tolerates_missing_blocks(self):
        s = soak.parse_diagnostics_payload(
            {}, elapsed_s=0.5, http_status=200
        )
        assert s.fetch_ok is True
        assert s.memory_pct is None
        assert s.disk_pct is None
        assert s.uptime_s is None
        assert s.refresh_running is None
        assert s.plugin_health == {}

    def test_non_dict_is_failure(self):
        s = soak.parse_diagnostics_payload(
            "not-a-dict", elapsed_s=0.1, http_status=200
        )
        assert s.fetch_ok is False
        assert s.fetch_error == "non-dict payload"

    def test_plugin_health_filters_non_strings(self):
        # A forward-compat diagnostics build might return richer shapes per
        # plugin. The runner should drop those rather than crash.
        payload = _payload(plugin_health={"clock": "ok", "weather": {"status": "fail"}})
        s = soak.parse_diagnostics_payload(payload, elapsed_s=0.0, http_status=200)
        assert s.plugin_health == {"clock": "ok"}


# ---------------------------------------------------------------------------
# Trend + summary
# ---------------------------------------------------------------------------


def _mk_sample(
    *,
    t: float,
    ok: bool = True,
    memory_pct: float | None = 50.0,
    disk_pct: float | None = 30.0,
    uptime_s: int | None = 1000,
    refresh_last_error: str | None = None,
    client_log_count_5m: int | None = 0,
    client_log_warn_count_5m: int | None = 0,
    fetch_error: str | None = None,
) -> "soak.Sample":
    return soak.Sample(
        ts=f"2026-04-19T00:{int(t):02d}:00+00:00",
        elapsed_s=t,
        fetch_ok=ok,
        fetch_error=fetch_error,
        http_status=200 if ok else None,
        version="0.61.7",
        uptime_s=uptime_s if ok else None,
        memory_pct=memory_pct if ok else None,
        disk_pct=disk_pct if ok else None,
        refresh_running=True if ok else None,
        refresh_last_error=refresh_last_error if ok else None,
        client_log_count_5m=client_log_count_5m if ok else None,
        client_log_warn_count_5m=client_log_warn_count_5m if ok else None,
        plugin_health={},
    )


class TestTrendSummary:
    def test_monotonic_leak_shows_positive_slope(self):
        # Simulate a slow leak: 50% -> 62% over 1 hour (3600s). Slope per
        # hour must be very close to +12.
        samples = [
            _mk_sample(t=i * 300.0, memory_pct=50.0 + (12.0 * i / 12.0))
            for i in range(13)  # 0..12 → 13 samples across 1 hour
        ]
        summary = soak.summarize_samples(samples)
        trend = summary["memory_pct_trend"]
        assert trend["n"] == 13
        assert trend["first"] == pytest.approx(50.0)
        assert trend["last"] == pytest.approx(62.0)
        assert trend["slope_per_hour"] == pytest.approx(12.0, rel=1e-6)
        assert trend["slope_per_second"] == pytest.approx(12.0 / 3600.0, rel=1e-6)

    def test_flat_shows_zero_slope(self):
        samples = [_mk_sample(t=i * 60.0, memory_pct=42.0) for i in range(10)]
        trend = soak.summarize_samples(samples)["memory_pct_trend"]
        assert trend["slope_per_hour"] == pytest.approx(0.0, abs=1e-9)

    def test_single_sample_has_no_slope(self):
        trend = soak.summarize_samples([_mk_sample(t=0.0)])["memory_pct_trend"]
        assert trend["n"] == 1
        assert trend["slope_per_hour"] is None
        assert trend["slope_per_second"] is None

    def test_no_samples_safe(self):
        summary = soak.summarize_samples([])
        assert summary["total_samples"] == 0
        assert summary["successful_samples"] == 0
        assert summary["unreachable_samples"] == 0
        assert summary["unreachable_rate"] == 0.0
        assert summary["service_restarts"] == 0
        assert summary["memory_pct_trend"]["n"] == 0
        assert summary["memory_pct_trend"]["slope_per_hour"] is None


class TestSummaryAggregates:
    def test_unreachable_counted_but_excluded_from_trend(self):
        # Two good samples, one unreachable between them. The unreachable
        # must not corrupt the memory trend computation.
        samples = [
            _mk_sample(t=0.0, memory_pct=50.0),
            _mk_sample(t=300.0, ok=False, fetch_error="timeout"),
            _mk_sample(t=600.0, memory_pct=52.0),
        ]
        summary = soak.summarize_samples(samples)
        assert summary["total_samples"] == 3
        assert summary["successful_samples"] == 2
        assert summary["unreachable_samples"] == 1
        assert summary["unreachable_rate"] == pytest.approx(1 / 3)
        assert summary["memory_pct_trend"]["n"] == 2
        assert summary["memory_pct_trend"]["first"] == pytest.approx(50.0)
        assert summary["memory_pct_trend"]["last"] == pytest.approx(52.0)

    def test_refresh_failure_rate(self):
        samples = [
            _mk_sample(t=0.0, refresh_last_error=None),
            _mk_sample(t=300.0, refresh_last_error="boom"),
            _mk_sample(t=600.0, refresh_last_error="boom"),
            _mk_sample(t=900.0, refresh_last_error=None),
        ]
        summary = soak.summarize_samples(samples)
        assert summary["refresh_failure_count"] == 2
        assert summary["refresh_failure_rate"] == pytest.approx(0.5)

    def test_client_log_totals_sum(self):
        samples = [
            _mk_sample(t=0.0, client_log_count_5m=0, client_log_warn_count_5m=1),
            _mk_sample(t=300.0, client_log_count_5m=3, client_log_warn_count_5m=2),
            _mk_sample(t=600.0, client_log_count_5m=5, client_log_warn_count_5m=0),
        ]
        summary = soak.summarize_samples(samples)
        assert summary["client_log_error_total"] == 8
        assert summary["client_log_warn_total"] == 3

    def test_service_restart_detected_on_uptime_regression(self):
        samples = [
            _mk_sample(t=0.0, uptime_s=1000),
            _mk_sample(t=300.0, uptime_s=1300),
            # Reboot: uptime resets to 10s.
            _mk_sample(t=600.0, uptime_s=10),
            _mk_sample(t=900.0, uptime_s=310),
        ]
        summary = soak.summarize_samples(samples)
        assert summary["service_restarts"] == 1

    def test_unreachable_samples_dont_trigger_restarts(self):
        # An unreachable window should not be counted as a restart on its
        # own — only a subsequent uptime regression should.
        samples = [
            _mk_sample(t=0.0, uptime_s=1000),
            _mk_sample(t=300.0, ok=False, fetch_error="timeout"),
            _mk_sample(t=600.0, uptime_s=1600),  # uptime grew through the blip
        ]
        summary = soak.summarize_samples(samples)
        assert summary["service_restarts"] == 0
        assert summary["unreachable_samples"] == 1


# ---------------------------------------------------------------------------
# build_report shape
# ---------------------------------------------------------------------------


class TestBuildReport:
    def test_report_shape(self):
        samples = [
            _mk_sample(t=0.0, memory_pct=50.0, disk_pct=30.0),
            _mk_sample(t=300.0, memory_pct=51.0, disk_pct=30.0),
        ]
        report = soak.build_report(
            host="http://pi.local",
            duration_s=600,
            interval_s=300,
            samples=samples,
            started_at="2026-04-19T00:00:00+00:00",
            ended_at="2026-04-19T00:10:00+00:00",
        )
        assert set(report.keys()) == {"meta", "samples", "summary"}
        assert report["meta"]["host"] == "http://pi.local"
        assert report["meta"]["duration_s"] == 600
        assert report["meta"]["sample_interval_s"] == 300
        assert report["meta"]["sample_count"] == 2
        assert len(report["samples"]) == 2
        # Each sample dict carries all the documented keys.
        sample_keys = set(report["samples"][0].keys())
        assert {
            "ts",
            "elapsed_s",
            "fetch_ok",
            "memory_pct",
            "disk_pct",
            "refresh_running",
            "refresh_last_error",
            "client_log_count_5m",
            "plugin_health",
        }.issubset(sample_keys)
        # Summary carries the trend blocks + aggregates used by reviewers.
        summary_keys = set(report["summary"].keys())
        assert {
            "total_samples",
            "successful_samples",
            "unreachable_samples",
            "unreachable_rate",
            "refresh_failure_rate",
            "client_log_error_total",
            "service_restarts",
            "memory_pct_trend",
            "disk_pct_trend",
        }.issubset(summary_keys)


# ---------------------------------------------------------------------------
# run_soak — integration with injected session / clock
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _FakeSession:
    """Session stub that serves canned payloads in order."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    def get(self, url, headers=None, timeout=None):  # noqa: D401 - stub
        self.calls.append((url, dict(headers or {})))
        if not self._responses:
            raise RuntimeError("no more canned responses")
        nxt = self._responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


class TestRunSoakLoop:
    def test_collects_samples_and_handles_transient_failure(self):
        # Three sample windows: success, network error, success.
        responses = [
            _FakeResponse(200, _payload(uptime_s=100, memory={"total_mb": 512, "used_mb": 256, "pct": 50.0}, disk={"total_mb": 16000, "used_mb": 5000, "pct": 31.0, "path": "/"})),
            ConnectionError("simulated wedge"),
            _FakeResponse(200, _payload(uptime_s=700, memory={"total_mb": 512, "used_mb": 280, "pct": 55.0}, disk={"total_mb": 16000, "used_mb": 5000, "pct": 31.0, "path": "/"})),
        ]
        session = _FakeSession(responses)

        # Virtual clock: each call to `now()` steps forward by 1s so the
        # loop's "next_tick" logic always fires a fresh sample. We return
        # 0, 1, 2, ... and cap duration at 3s for three iterations.
        clock = {"t": 0.0}

        def fake_now():
            return clock["t"]

        def fake_sleep(seconds):
            # Advance the virtual clock by whatever was requested.
            clock["t"] += max(float(seconds), 0.0)

        # Drive the loop by stepping the clock manually between samples.
        # To get exactly 3 samples at interval=1s, duration=3s, we run the
        # loop and let it terminate naturally — each `sleep()` advances time.
        samples = soak.run_soak(
            host="http://pi.local",
            duration_s=3,
            interval_s=1,
            session=session,
            now=fake_now,
            sleep=fake_sleep,
            request_timeout_s=5,
        )

        assert len(samples) == 3
        assert samples[0].fetch_ok is True
        assert samples[0].memory_pct == 50.0
        assert samples[1].fetch_ok is False
        assert "simulated wedge" in (samples[1].fetch_error or "")
        assert samples[2].fetch_ok is True
        assert samples[2].uptime_s == 700
        # All calls hit the diagnostics endpoint.
        assert all(url.endswith("/api/diagnostics") for url, _ in session.calls)

    def test_token_is_forwarded_in_headers(self):
        session = _FakeSession([_FakeResponse(200, _payload())])
        clock = {"t": 0.0}

        def fake_now():
            return clock["t"]

        def fake_sleep(seconds):
            clock["t"] += max(float(seconds), 0.0)

        soak.run_soak(
            host="http://pi.local/",  # trailing slash should be stripped
            duration_s=1,
            interval_s=1,
            token="tok-123",
            session=session,
            now=fake_now,
            sleep=fake_sleep,
        )
        assert session.calls
        url, headers = session.calls[0]
        assert url == "http://pi.local/api/diagnostics"
        assert headers.get("Authorization") == "Bearer tok-123"
        assert headers.get("X-InkyPi-Token") == "tok-123"


# ---------------------------------------------------------------------------
# CLI argument handling
# ---------------------------------------------------------------------------


class TestCLI:
    def test_invalid_duration_returns_2(self, capsys):
        rc = soak.main(["--duration", "nope"])
        assert rc == 2
        assert "invalid duration" in capsys.readouterr().err

    def test_interval_larger_than_duration_rejected(self, capsys):
        rc = soak.main(["--duration", "10s", "--interval", "1m"])
        assert rc == 2
        assert "interval" in capsys.readouterr().err
