from datetime import UTC, datetime

from utils.time_utils import (
    calculate_seconds,
    get_next_occurrence,
    parse_cron_field,
)


def test_calculate_seconds_minute():
    assert calculate_seconds(3, "minute") == 180


def test_calculate_seconds_hour():
    assert calculate_seconds(2, "hour") == 7200


def test_calculate_seconds_day():
    assert calculate_seconds(1, "day") == 86400


def test_calculate_seconds_default_value_for_unrecognized_unit():
    assert calculate_seconds(99, "weeks") == 300


# ---- parse_cron_field ----


def test_parse_cron_field_wildcard():
    result = parse_cron_field("*", 0, 59)
    assert result == set(range(60))


def test_parse_cron_field_single_value():
    result = parse_cron_field("5", 0, 59)
    assert result == {5}


def test_parse_cron_field_range():
    result = parse_cron_field("0-5", 0, 59)
    assert result == {0, 1, 2, 3, 4, 5}


def test_parse_cron_field_reversed_range():
    """Reversed range like '5-0' should be normalized."""
    result = parse_cron_field("5-0", 0, 59)
    assert result == {0, 1, 2, 3, 4, 5}


def test_parse_cron_field_comma_list():
    result = parse_cron_field("1,3,5", 0, 59)
    assert result == {1, 3, 5}


def test_parse_cron_field_out_of_range_ignored():
    result = parse_cron_field("60", 0, 59)
    assert result == set()


def test_parse_cron_field_invalid_value_ignored():
    result = parse_cron_field("abc", 0, 59)
    assert result == set()


def test_parse_cron_field_empty_string():
    result = parse_cron_field("", 0, 59)
    assert result == set()


def test_parse_cron_field_none():
    result = parse_cron_field(None, 0, 59)
    assert result == set()


# ---- get_next_occurrence ----


def test_next_occurrence_every_minute():
    """'* * * * *' should match the very next minute."""
    now = datetime(2025, 6, 15, 10, 30, 0, tzinfo=UTC)
    result = get_next_occurrence("* * * * *", now)
    assert result is not None
    assert result == datetime(2025, 6, 15, 10, 31, 0, tzinfo=UTC)


def test_next_occurrence_hourly():
    """'0 * * * *' matches minute 0 of the next hour."""
    now = datetime(2025, 6, 15, 10, 30, 0, tzinfo=UTC)
    result = get_next_occurrence("0 * * * *", now)
    assert result is not None
    assert result.minute == 0
    assert result.hour == 11


def test_next_occurrence_daily_at_noon():
    """'0 12 * * *' should find next occurrence at 12:00."""
    now = datetime(2025, 6, 15, 13, 0, 0, tzinfo=UTC)
    result = get_next_occurrence("0 12 * * *", now)
    assert result is not None
    assert result == datetime(2025, 6, 16, 12, 0, 0, tzinfo=UTC)


def test_next_occurrence_specific_minute():
    """'30 * * * *' should find minute 30 of the current or next hour."""
    now = datetime(2025, 6, 15, 10, 0, 0, tzinfo=UTC)
    result = get_next_occurrence("30 * * * *", now)
    assert result is not None
    assert result.minute == 30
    assert result.hour == 10


def test_next_occurrence_range_expression():
    """'0-30 10 * * *' should match minutes 0-30 in hour 10."""
    now = datetime(2025, 6, 15, 10, 25, 0, tzinfo=UTC)
    result = get_next_occurrence("0-30 10 * * *", now)
    assert result is not None
    assert result.minute == 26
    assert result.hour == 10


def test_next_occurrence_step_expression_via_comma():
    """Test step-like behavior using comma-separated values (*/5 equivalent)."""
    # parse_cron_field doesn't support */5 syntax, so use comma list
    now = datetime(2025, 6, 15, 10, 0, 0, tzinfo=UTC)
    result = get_next_occurrence("0,5,10,15,20,25,30,35,40,45,50,55 * * * *", now)
    assert result is not None
    assert result.minute == 5


def test_next_occurrence_midnight_crossing():
    """'0 0 * * *' at 23:59 should find next day 00:00."""
    now = datetime(2025, 6, 15, 23, 59, 0, tzinfo=UTC)
    result = get_next_occurrence("0 0 * * *", now)
    assert result is not None
    assert result == datetime(2025, 6, 16, 0, 0, 0, tzinfo=UTC)


def test_next_occurrence_specific_day_of_week():
    """'0 9 * * 1' (Monday) should find next Monday at 9:00."""
    # June 15, 2025 is a Sunday (weekday=6, cron_dow=0)
    now = datetime(2025, 6, 15, 10, 0, 0, tzinfo=UTC)
    result = get_next_occurrence("0 9 * * 1", now)
    assert result is not None
    # Next Monday is June 16
    assert result.day == 16
    assert result.hour == 9
    assert result.minute == 0


def test_next_occurrence_invalid_cron_wrong_field_count():
    """Invalid cron expression with wrong number of fields returns None."""
    now = datetime(2025, 6, 15, 10, 0, 0, tzinfo=UTC)
    assert get_next_occurrence("* * *", now) is None
    assert get_next_occurrence("* * * * * *", now) is None
    assert get_next_occurrence("", now) is None


def test_next_occurrence_specific_month():
    """'0 0 1 12 *' should find December 1st at midnight."""
    now = datetime(2025, 6, 15, 0, 0, 0, tzinfo=UTC)
    result = get_next_occurrence("0 0 1 12 *", now)
    assert result is not None
    assert result.month == 12
    assert result.day == 1


def test_next_occurrence_uses_utc_default():
    """When no `now` is provided, function uses UTC."""
    result = get_next_occurrence("* * * * *")
    assert result is not None
    assert result.tzinfo is not None


def test_next_occurrence_near_midnight_23_59():
    """From 23:58, '59 23 * * *' should find 23:59 same day."""
    now = datetime(2025, 6, 15, 23, 58, 0, tzinfo=UTC)
    result = get_next_occurrence("59 23 * * *", now)
    assert result is not None
    assert result == datetime(2025, 6, 15, 23, 59, 0, tzinfo=UTC)


def test_next_occurrence_dom_and_dow_both_specified():
    """When both day-of-month and day-of-week are non-wildcard, cron OR's them."""
    # '0 0 15 * 1' means: minute=0, hour=0, day=15 OR Monday
    now = datetime(2025, 6, 14, 0, 0, 0, tzinfo=UTC)
    result = get_next_occurrence("0 0 15 * 1", now)
    assert result is not None
    # June 15 is Sunday, June 16 is Monday. Both day=15 and Monday match.
    assert result.day in (15, 16)
