from datetime import datetime

from blueprints.main import _current_dt


def test_current_dt_returns_now_device_tz(monkeypatch):
    sentinel = datetime(2020, 1, 1)

    def fake(device_config):
        return sentinel

    monkeypatch.setattr("utils.time_utils.now_device_tz", fake, raising=True)

    assert _current_dt(object()) is sentinel


def test_current_dt_falls_back_to_utc(monkeypatch):
    def boom(device_config):
        raise RuntimeError("fail")

    monkeypatch.setattr("utils.time_utils.now_device_tz", boom, raising=True)

    result = _current_dt(object())
    assert isinstance(result, datetime)
    assert result.tzinfo is None
    assert abs((result - datetime.utcnow()).total_seconds()) < 5
