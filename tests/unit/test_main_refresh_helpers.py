"""Unit tests for the dashboard refresh-schedule helpers in blueprints.main.

These helpers shape the refresh-info payload used by the dashboard template
and by ``/api/refresh-info``. They are pure (no Flask context, no global
state) so they can be exercised directly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from zoneinfo import ZoneInfo

import pytest

from blueprints.main import (
    _annotate_refresh_schedule,
    _build_next_refresh_meta,
    _format_next_refresh_relative,
    _parse_refresh_datetime,
    _playlist_cycle_seconds,
)

if TYPE_CHECKING:
    from config import Config

# ---------------------------------------------------------------------------
# _playlist_cycle_seconds — the loop's cycle for the last refresh's playlist
# ---------------------------------------------------------------------------


def _device_with_playlist(device_seconds: int, playlist: Any) -> Any:
    pm = SimpleNamespace(get_playlist=lambda name: playlist)

    class _Cfg:
        def get_config(self, key: str, default: Any = None) -> Any:
            return device_seconds

        def get_playlist_manager(self) -> Any:
            return pm

    return _Cfg()


def test_playlist_cycle_uses_device_when_name_missing() -> None:
    cfg = _device_with_playlist(600, playlist=None)
    assert _playlist_cycle_seconds(cfg, "") == 600
    assert _playlist_cycle_seconds(cfg, None) == 600


def test_playlist_cycle_uses_playlist_override_when_set() -> None:
    playlist = SimpleNamespace(cycle_interval_seconds=300)
    cfg = _device_with_playlist(3600, playlist=playlist)
    assert _playlist_cycle_seconds(cfg, "Focus") == 300


def test_playlist_cycle_falls_back_to_device_when_playlist_missing() -> None:
    cfg = _device_with_playlist(1800, playlist=None)
    assert _playlist_cycle_seconds(cfg, "Ghost") == 1800


def test_playlist_cycle_falls_back_on_playlist_manager_error() -> None:
    class _Cfg:
        def get_config(self, key: str, default: Any = None) -> Any:
            return 3600

        def get_playlist_manager(self) -> Any:
            raise RuntimeError("playlist_manager unavailable")

    assert _playlist_cycle_seconds(cast("Config", _Cfg()), "Focus") == 3600


def test_sub_minute_cycle_reads_one_minute_not_zero(monkeypatch: Any) -> None:
    # 30 // 60 == 0 would print "Every 0 min".
    monkeypatch.setattr(
        "blueprints.main.now_device_tz", lambda cfg: datetime(2025, 1, 1, tzinfo=UTC)
    )
    playlist = SimpleNamespace(cycle_interval_seconds=30)
    cfg = _device_with_playlist(3600, playlist=playlist)

    result = _annotate_refresh_schedule({"playlist": "Focus"}, cfg)

    assert result["cycle_minutes"] == 1


# ---------------------------------------------------------------------------
# _parse_refresh_datetime
# ---------------------------------------------------------------------------


def test_parse_refresh_datetime_returns_none_for_empty() -> None:
    assert _parse_refresh_datetime(None) is None
    assert _parse_refresh_datetime("") is None


def test_parse_refresh_datetime_returns_none_for_invalid_iso() -> None:
    assert _parse_refresh_datetime("not a timestamp") is None


def test_parse_refresh_datetime_preserves_aware_input() -> None:
    parsed = _parse_refresh_datetime("2025-01-01T08:00:00+00:00")
    assert parsed is not None
    assert parsed.tzinfo is not None
    assert parsed == datetime(2025, 1, 1, 8, 0, tzinfo=UTC)


def test_parse_refresh_datetime_assumes_utc_for_naive_input() -> None:
    parsed = _parse_refresh_datetime("2025-01-01T08:00:00")
    assert parsed is not None
    assert parsed.tzinfo is UTC


# ---------------------------------------------------------------------------
# _format_next_refresh_relative
# ---------------------------------------------------------------------------


@pytest.fixture
def now_utc() -> datetime:
    return datetime(2025, 1, 1, 8, 0, tzinfo=UTC)


def test_format_next_refresh_relative_due_now(now_utc: datetime) -> None:
    # Anything within 30 seconds reads as "Due now".
    assert _format_next_refresh_relative(now_utc, now_utc) == "Due now"
    assert (
        _format_next_refresh_relative(
            now_utc.replace(second=20), now_utc.replace(second=0)
        )
        == "Due now"
    )


def test_format_next_refresh_relative_seconds(now_utc: datetime) -> None:
    target = now_utc.replace(second=45)
    assert _format_next_refresh_relative(target, now_utc) == "in 45s"


def test_format_next_refresh_relative_minutes(now_utc: datetime) -> None:
    target = now_utc.replace(minute=5)
    assert _format_next_refresh_relative(target, now_utc) == "in 5m"


def test_format_next_refresh_relative_hours(now_utc: datetime) -> None:
    target = now_utc.replace(hour=10)
    assert _format_next_refresh_relative(target, now_utc) == "in 2h"


def test_format_next_refresh_relative_hours_with_minutes(now_utc: datetime) -> None:
    target = now_utc.replace(hour=10, minute=30)
    assert _format_next_refresh_relative(target, now_utc) == "in 2h 30m"


def test_format_next_refresh_relative_day_plus_falls_back_to_local_time() -> None:
    tz = ZoneInfo("UTC")
    now = datetime(2025, 1, 1, 8, 0, tzinfo=tz)
    target = datetime(2025, 1, 3, 17, 5, tzinfo=tz)
    formatted = _format_next_refresh_relative(target, now)
    # The exact format ("5:05 PM") depends on the local hour format, but it
    # must not fall back to a bare "in Nh" for multi-day gaps.
    assert formatted.startswith("at ")
    assert "PM" in formatted or "AM" in formatted


# ---------------------------------------------------------------------------
# _build_next_refresh_meta
# ---------------------------------------------------------------------------


def test_build_next_refresh_meta_with_full_payload(now_utc: datetime) -> None:
    target = now_utc.replace(hour=9, minute=0)
    meta = _build_next_refresh_meta(target, cycle_minutes=15, now_dt=now_utc)
    assert "ETA " in meta
    assert "Every 15 min" in meta
    assert meta.endswith("auto")


def test_build_next_refresh_meta_without_target_omits_eta(now_utc: datetime) -> None:
    meta = _build_next_refresh_meta(None, cycle_minutes=30, now_dt=now_utc)
    assert "ETA" not in meta
    assert "Every 30 min" in meta
    assert meta.endswith("auto")


def test_build_next_refresh_meta_without_cycle_keeps_auto(now_utc: datetime) -> None:
    target = now_utc.replace(hour=9, minute=0)
    meta = _build_next_refresh_meta(target, cycle_minutes=0, now_dt=now_utc)
    # cycle_minutes == 0 means the "Every X min" line is dropped.
    assert "Every" not in meta
    assert meta.endswith("auto")


# ---------------------------------------------------------------------------
# _annotate_refresh_schedule
# ---------------------------------------------------------------------------


def test_annotate_refresh_schedule_passes_through_non_dict(monkeypatch: Any) -> None:
    cfg = _device_with_playlist(3600, playlist=None)
    assert _annotate_refresh_schedule(None, cfg) is None
    assert _annotate_refresh_schedule("refresh-info", cfg) == "refresh-info"


def test_annotate_refresh_schedule_handles_missing_refresh_time(
    monkeypatch: Any,
) -> None:
    fixed_now = datetime(2025, 1, 1, 8, 0, tzinfo=UTC)
    monkeypatch.setattr("blueprints.main.now_device_tz", lambda cfg: fixed_now)

    cfg = _device_with_playlist(900, playlist=None)
    payload: dict[str, Any] = {"playlist": None, "refresh_time": None}

    result = _annotate_refresh_schedule(payload, cfg)

    assert result is payload
    assert result["cycle_minutes"] == 15
    assert result["next_refresh_time"] is None
    assert result["next_refresh_relative"] is None
    assert "Every 15 min" in result["next_refresh_meta"]
    assert "ETA" not in result["next_refresh_meta"]


def test_annotate_refresh_schedule_projects_next_refresh(monkeypatch: Any) -> None:
    fixed_now = datetime(2025, 1, 1, 7, 57, tzinfo=UTC)
    monkeypatch.setattr("blueprints.main.now_device_tz", lambda cfg: fixed_now)

    playlist = SimpleNamespace(cycle_interval_seconds=300)  # 5-minute override
    pm = SimpleNamespace(get_playlist=lambda name: playlist)

    class _Cfg:
        def get_config(self, key: str, default: Any = None) -> Any:
            return 3600

        def get_playlist_manager(self) -> Any:
            return pm

    payload: dict[str, Any] = {
        "playlist": "Focus",
        "refresh_time": "2025-01-01T07:55:00+00:00",
    }

    result = _annotate_refresh_schedule(payload, cast("Config", _Cfg()))

    assert result["cycle_minutes"] == 5
    assert result["next_refresh_time"] == "2025-01-01T08:00:00+00:00"
    # 3 minutes ahead of fixed_now → the relative label should be "in 3m".
    assert result["next_refresh_relative"] == "in 3m"
    assert "ETA" in result["next_refresh_meta"]
    assert "Every 5 min" in result["next_refresh_meta"]


def test_annotate_refresh_schedule_counts_a_failed_attempt(monkeypatch: Any) -> None:
    # The 07:55 refresh succeeded; the loop's 08:00 turn failed, so it next
    # acts at 08:05. The dashboard must say so, not "Due now" until then.
    fixed_now = datetime(2025, 1, 1, 8, 1, tzinfo=UTC)
    monkeypatch.setattr("blueprints.main.now_device_tz", lambda cfg: fixed_now)
    cfg = _device_with_playlist(300, playlist=None)
    payload: dict[str, Any] = {"refresh_time": "2025-01-01T07:55:00+00:00"}

    result = _annotate_refresh_schedule(
        payload, cfg, last_attempt=datetime(2025, 1, 1, 8, 0, tzinfo=UTC)
    )

    assert result["next_refresh_time"] == "2025-01-01T08:05:00+00:00"
    assert result["next_refresh_relative"] == "in 4m"


def test_annotate_refresh_schedule_uses_seconds_not_floored_minutes(
    monkeypatch: Any,
) -> None:
    # A 90-second cycle is due 90 s after the refresh, not 60.
    fixed_now = datetime(2025, 1, 1, 8, 0, tzinfo=UTC)
    monkeypatch.setattr("blueprints.main.now_device_tz", lambda cfg: fixed_now)
    cfg = _device_with_playlist(90, playlist=None)

    result = _annotate_refresh_schedule(
        {"refresh_time": "2025-01-01T08:00:00+00:00"}, cfg
    )

    assert result["next_refresh_time"] == "2025-01-01T08:01:30+00:00"


def test_annotate_refresh_schedule_converts_next_to_device_timezone(
    monkeypatch: Any,
) -> None:
    # Simulate a device running in a non-UTC timezone (America/New_York).
    ny = ZoneInfo("America/New_York")
    fixed_now = datetime(2025, 1, 1, 2, 57, tzinfo=ny)
    monkeypatch.setattr("blueprints.main.now_device_tz", lambda cfg: fixed_now)

    cfg = _device_with_playlist(900, playlist=None)
    payload: dict[str, Any] = {
        "playlist": None,
        "refresh_time": "2025-01-01T07:50:00+00:00",  # 02:50 America/New_York
    }

    result = _annotate_refresh_schedule(payload, cfg)

    # refresh at 02:50 + 15m cycle = 03:05 America/New_York (i.e. 08:05 UTC).
    next_iso = result["next_refresh_time"]
    parsed = datetime.fromisoformat(next_iso)
    assert parsed.astimezone(ny).hour == 3
    assert parsed.astimezone(ny).minute == 5
    # Regression guard: the isoformat uses the device-tz offset, not UTC.
    assert parsed.utcoffset() != UTC.utcoffset(None)
