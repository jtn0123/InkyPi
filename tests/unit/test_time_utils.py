from utils.time_utils import calculate_seconds


def test_calculate_seconds_minute():
    assert calculate_seconds(3, "minute") == 180


def test_calculate_seconds_hour():
    assert calculate_seconds(2, "hour") == 7200


def test_calculate_seconds_day():
    assert calculate_seconds(1, "day") == 86400


def test_calculate_seconds_default_value_for_unrecognized_unit():
    assert calculate_seconds(99, "weeks") == 300
