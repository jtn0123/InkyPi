"""Unit tests for the sidebar label helpers in ``src/inkypi.py``.

The helpers are pure and do not require Flask context, so they can be
exercised directly. These tests anchor the calendar-date bucketing that
replaced the elapsed-seconds heuristic (JTN handoff parity) and guard
against regressions when ``getloadavg`` is unavailable.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from inkypi import (
    _format_sidebar_load_average,
    _format_sidebar_refresh_time,
    _parse_refresh_datetime,
)


# ---------------------------------------------------------------------------
# _parse_refresh_datetime
# ---------------------------------------------------------------------------


def test_parse_refresh_datetime_rejects_non_strings() -> None:
    assert _parse_refresh_datetime(None) is None
    assert _parse_refresh_datetime(12345) is None
    assert _parse_refresh_datetime("") is None


def test_parse_refresh_datetime_rejects_invalid_iso() -> None:
    assert _parse_refresh_datetime("not a timestamp") is None


def test_parse_refresh_datetime_preserves_aware_input() -> None:
    parsed = _parse_refresh_datetime("2025-01-01T08:00:00+00:00")
    assert parsed == datetime(2025, 1, 1, 8, 0, tzinfo=UTC)


def test_parse_refresh_datetime_assumes_utc_for_naive_input() -> None:
    parsed = _parse_refresh_datetime("2025-01-01T08:00:00")
    assert parsed is not None
    assert parsed.tzinfo is UTC


# ---------------------------------------------------------------------------
# _format_sidebar_refresh_time
# ---------------------------------------------------------------------------


@pytest.fixture
def patched_now(monkeypatch: Any) -> Any:
    """Force ``utils.time_utils.now_device_tz`` to return a fixed instant."""

    def _patch(fixed: datetime) -> None:
        monkeypatch.setattr(
            "utils.time_utils.now_device_tz", lambda cfg: fixed, raising=True
        )

    return _patch


def test_format_sidebar_refresh_time_returns_none_for_missing_input() -> None:
    assert _format_sidebar_refresh_time(None, None) is None
    assert _format_sidebar_refresh_time("", None) is None


def test_format_sidebar_refresh_time_just_now(patched_now: Any) -> None:
    now = datetime(2025, 1, 1, 8, 0, tzinfo=UTC)
    patched_now(now)
    assert (
        _format_sidebar_refresh_time("2025-01-01T07:59:30+00:00", object())
        == "just now"
    )


def test_format_sidebar_refresh_time_minutes(patched_now: Any) -> None:
    now = datetime(2025, 1, 1, 8, 45, tzinfo=UTC)
    patched_now(now)
    assert (
        _format_sidebar_refresh_time("2025-01-01T08:15:00+00:00", object())
        == "30 min ago"
    )


def test_format_sidebar_refresh_time_today(patched_now: Any) -> None:
    # Same local date, >60 minutes ago → "today at …".
    now = datetime(2025, 1, 1, 14, 0, tzinfo=UTC)
    patched_now(now)
    label = _format_sidebar_refresh_time("2025-01-01T09:00:00+00:00", object())
    assert label is not None
    assert label.startswith("today at ")


def test_format_sidebar_refresh_time_yesterday_by_calendar_date(
    patched_now: Any,
) -> None:
    # Regression guard: an 8am refresh of a 23:00-last-night event must read
    # as "yesterday", not "today" under the old elapsed-seconds heuristic.
    now = datetime(2025, 1, 2, 8, 0, tzinfo=UTC)
    patched_now(now)
    label = _format_sidebar_refresh_time("2025-01-01T23:00:00+00:00", object())
    assert label is not None
    assert label.startswith("yesterday at ")


def test_format_sidebar_refresh_time_older_than_yesterday_uses_month_day(
    patched_now: Any,
) -> None:
    now = datetime(2025, 1, 10, 8, 0, tzinfo=UTC)
    patched_now(now)
    label = _format_sidebar_refresh_time("2025-01-05T08:00:00+00:00", object())
    assert label is not None
    # "Jan 5 at 8:00 AM" — no leading zero on the day number.
    assert "Jan 5" in label
    assert " at " in label


def test_format_sidebar_refresh_time_falls_back_when_timeutils_fails(
    monkeypatch: Any,
) -> None:
    """If ``now_device_tz`` blows up, we fall back to datetime.now(tz)."""

    def boom(cfg: Any) -> Any:
        raise RuntimeError("time_utils unavailable")

    monkeypatch.setattr("utils.time_utils.now_device_tz", boom, raising=True)
    # Any plausible recent timestamp — the only invariant we care about here
    # is that the function returns *something* rather than propagating.
    result = _format_sidebar_refresh_time(
        datetime.now(UTC).isoformat(), object()
    )
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# _format_sidebar_load_average
# ---------------------------------------------------------------------------


def test_format_sidebar_load_average_returns_label(monkeypatch: Any) -> None:
    monkeypatch.setattr("os.getloadavg", lambda: (1.25, 0.9, 0.5))
    assert _format_sidebar_load_average() == "1.25 avg"


def test_format_sidebar_load_average_handles_missing_getloadavg(
    monkeypatch: Any,
) -> None:
    def raise_attr() -> tuple[float, float, float]:
        raise AttributeError("getloadavg unavailable on this platform")

    monkeypatch.setattr("os.getloadavg", raise_attr)
    assert _format_sidebar_load_average() is None


def test_format_sidebar_load_average_handles_oserror(monkeypatch: Any) -> None:
    def raise_os() -> tuple[float, float, float]:
        raise OSError("read failed")

    monkeypatch.setattr("os.getloadavg", raise_os)
    assert _format_sidebar_load_average() is None
