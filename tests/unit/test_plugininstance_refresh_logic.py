from datetime import UTC, datetime, timedelta, timezone

from model import PluginInstance


def test_should_refresh_interval_and_initial():
    inst = PluginInstance("x", "A", {}, {"interval": 60}, latest_refresh_time=None)
    now = datetime.now(UTC)
    # No latest -> should refresh
    assert inst.should_refresh(now) is True

    # Set last refresh to long ago -> should refresh
    inst.latest_refresh_time = (now - timedelta(seconds=120)).isoformat()
    assert inst.should_refresh(now) is True

    # Set last refresh recent -> may not refresh
    inst.latest_refresh_time = (now - timedelta(seconds=10)).isoformat()
    assert inst.should_refresh(now) is False


def test_should_refresh_scheduled_with_tz_alignment():
    # Schedule at current minute; last refresh earlier today should trigger
    now = datetime.now(UTC)
    hhmm = now.strftime("%H:%M")
    inst = PluginInstance(
        "x",
        "A",
        {},
        {"scheduled": hhmm},
        latest_refresh_time=(now - timedelta(hours=1)).isoformat(),
    )
    assert inst.should_refresh(now) is True

    # Last refresh after scheduled -> should not refresh
    inst.latest_refresh_time = (now + timedelta(minutes=1)).isoformat()
    assert inst.should_refresh(now) is False


# ---------------------------------------------------------------------------
# DST transition tests (JTN-268)
# ---------------------------------------------------------------------------
# We simulate DST transitions by using fixed-offset timezones that mimic the
# before/after UTC offset change.  Python's datetime.replace() on a naive-ish
# aware datetime *with a fixed offset* doesn't itself generate non-existent
# times, but the important thing is that our timedelta-based construction
# always yields the correct wall-clock value regardless of the UTC offset in
# effect at midnight vs. at the scheduled time.


def _tz(offset_hours: int) -> timezone:
    """Return a fixed-offset timezone for testing."""
    return timezone(timedelta(hours=offset_hours))


class TestDSTSpringForward:
    """Spring-forward: clocks jump from 02:00 → 03:00, so 02:30 never exists."""

    def test_scheduled_time_in_gap_still_fires_after_gap(self):
        """A plugin scheduled at 02:30 should fire once the clock is past 03:00.

        Before the fix, current_time.replace(hour=2, minute=30) on a datetime
        whose wall-clock is already past 03:00 with a UTC+3 offset (post-spring)
        would construct 02:30+03:00.  The timedelta approach constructs
        midnight + 2h30m which is the same conceptual wall time and is safe.
        """
        # Simulate the moment just after spring-forward: wall clock reads 03:05
        # UTC offset has jumped from +2 to +3 (1-hour spring-forward).
        post_spring_tz = _tz(3)
        # current_time is 03:05 in the new (post-spring) timezone
        current_time = datetime(2024, 3, 31, 3, 5, 0, tzinfo=post_spring_tz)
        # Last refresh was at 01:00 (well before the gap)
        last_refresh = datetime(2024, 3, 31, 1, 0, 0, tzinfo=post_spring_tz)

        inst = PluginInstance(
            "x",
            "A",
            {},
            {"scheduled": "02:30"},
            latest_refresh_time=last_refresh.isoformat(),
        )
        # scheduled_dt = midnight(03:05+03:00) + 2h30m = 2024-03-31 02:30+03:00
        # current_time 03:05 > 02:30, last_refresh 01:00 < 02:30 → should fire
        assert inst.should_refresh(current_time) is True

    def test_already_refreshed_at_gap_time_does_not_double_fire(self):
        """If the last refresh is recorded at 02:30, a second call should not fire."""
        post_spring_tz = _tz(3)
        current_time = datetime(2024, 3, 31, 3, 5, 0, tzinfo=post_spring_tz)
        # last refresh == scheduled time (already ran)
        last_refresh = datetime(2024, 3, 31, 2, 30, 0, tzinfo=post_spring_tz)

        inst = PluginInstance(
            "x",
            "A",
            {},
            {"scheduled": "02:30"},
            latest_refresh_time=last_refresh.isoformat(),
        )
        assert inst.should_refresh(current_time) is False


class TestDSTFallBack:
    """Fall-back: clocks repeat 01:00–02:00, so 01:30 appears twice.

    During a fall-back transition the UTC offsets differ between the two
    occurrences.  Each occurrence is a distinct UTC moment, so it is
    correct for the scheduler to fire at both — one at 01:30 EDT (UTC-4)
    and one at 01:30 EST (UTC-5).  The important invariant is that within
    a single timezone offset the scheduler does not double-fire.
    """

    def test_scheduled_time_fires_in_pre_fallback_hour(self):
        """Fires correctly during the first 01:30 (pre-fallback, UTC-4)."""
        pre_fallback_tz = _tz(-4)
        current_time = datetime(2024, 11, 3, 1, 45, 0, tzinfo=pre_fallback_tz)
        last_refresh = datetime(2024, 11, 3, 0, 0, 0, tzinfo=pre_fallback_tz)

        inst = PluginInstance(
            "x",
            "A",
            {},
            {"scheduled": "01:30"},
            latest_refresh_time=last_refresh.isoformat(),
        )
        # 01:30-04:00 is between 00:00 and 01:45 → should fire
        assert inst.should_refresh(current_time) is True

    def test_does_not_double_fire_in_same_offset_window(self):
        """After firing during the first 01:30 (UTC-4), does not fire again in that same window."""
        pre_fallback_tz = _tz(-4)
        # current is 01:45 EDT, refresh already happened at 01:30 EDT
        current_time = datetime(2024, 11, 3, 1, 45, 0, tzinfo=pre_fallback_tz)
        last_refresh = datetime(2024, 11, 3, 1, 30, 0, tzinfo=pre_fallback_tz)

        inst = PluginInstance(
            "x",
            "A",
            {},
            {"scheduled": "01:30"},
            latest_refresh_time=last_refresh.isoformat(),
        )
        # last_refresh == scheduled_dt (01:30 EDT) → condition is <=, not <, so False
        assert inst.should_refresh(current_time) is False

    def test_scheduled_time_fires_in_post_fallback_hour(self):
        """Fires correctly during the second 01:30 (post-fallback, UTC-5).

        The last refresh was at 01:30 EDT (UTC-4) = 05:30 UTC.
        The post-fallback scheduled_dt is 01:30 EST (UTC-5) = 06:30 UTC.
        These are different UTC moments so it is correct to fire again.
        """
        pre_fallback_tz = _tz(-4)
        post_fallback_tz = _tz(-5)

        # Refresh happened at 01:30 EDT
        last_refresh = datetime(2024, 11, 3, 1, 30, 0, tzinfo=pre_fallback_tz)
        # Now it is 01:45 EST (after clocks fell back)
        current_time = datetime(2024, 11, 3, 1, 45, 0, tzinfo=post_fallback_tz)

        inst = PluginInstance(
            "x",
            "A",
            {},
            {"scheduled": "01:30"},
            latest_refresh_time=last_refresh.isoformat(),
        )
        # last_refresh 05:30 UTC < scheduled_dt 06:30 UTC → should fire
        assert inst.should_refresh(current_time) is True

    def test_before_fallback_scheduled_time_does_not_fire_early(self):
        """Before the scheduled time, should_refresh returns False."""
        pre_fallback_tz = _tz(-4)
        # It's 01:00 (before 01:30)
        current_time = datetime(2024, 11, 3, 1, 0, 0, tzinfo=pre_fallback_tz)
        last_refresh = datetime(2024, 11, 3, 0, 0, 0, tzinfo=pre_fallback_tz)

        inst = PluginInstance(
            "x",
            "A",
            {},
            {"scheduled": "01:30"},
            latest_refresh_time=last_refresh.isoformat(),
        )
        assert inst.should_refresh(current_time) is False
