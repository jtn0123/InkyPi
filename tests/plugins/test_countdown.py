# pyright: reportMissingImports=false
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from PIL import Image


@pytest.fixture()
def plugin_config():
    return {"id": "countdown", "class": "Countdown", "name": "Countdown"}


def _frozen_now(year, month, day):
    return datetime(year, month, day, 12, 0, 0, tzinfo=UTC)


def test_countdown_future_date(plugin_config, device_config_dev):
    from plugins.countdown.countdown import Countdown

    with patch("plugins.countdown.countdown.datetime", wraps=datetime) as mock_dt:
        mock_dt.now.return_value = _frozen_now(2025, 6, 1)
        p = Countdown(plugin_config)
        result = p.generate_image(
            {"title": "Vacation", "date": "2025-12-25"},
            device_config_dev,
        )
    assert isinstance(result, Image.Image)


def test_countdown_past_date(plugin_config, device_config_dev):
    from plugins.countdown.countdown import Countdown

    with patch("plugins.countdown.countdown.datetime", wraps=datetime) as mock_dt:
        mock_dt.now.return_value = _frozen_now(2025, 6, 1)
        p = Countdown(plugin_config)
        result = p.generate_image(
            {"title": "Past Event", "date": "2025-01-01"},
            device_config_dev,
        )
    assert isinstance(result, Image.Image)


def test_countdown_today(plugin_config, device_config_dev):
    from plugins.countdown.countdown import Countdown

    with patch("plugins.countdown.countdown.datetime", wraps=datetime) as mock_dt:
        mock_dt.now.return_value = _frozen_now(2025, 6, 15)
        p = Countdown(plugin_config)
        result = p.generate_image(
            {"title": "Today", "date": "2025-06-15"},
            device_config_dev,
        )
    assert isinstance(result, Image.Image)


def test_countdown_missing_date_falls_back_to_default(plugin_config, device_config_dev):
    """JTN-784: missing/empty date renders with a ~30-day default rather than
    raising, so a bare /update_now call produces a visible render. Form-time
    validation (validate_settings) still rejects the empty date; see
    ``test_countdown_validate_settings_rejects_missing_date`` below."""
    from plugins.countdown.countdown import Countdown

    p = Countdown(plugin_config)
    result = p.generate_image({"title": "No Date"}, device_config_dev)
    assert isinstance(result, Image.Image)


def test_countdown_validate_settings_rejects_missing_date(plugin_config):
    from plugins.countdown.countdown import Countdown

    p = Countdown(plugin_config)
    assert p.validate_settings({"title": "No Date", "date": ""}) == "Date is required."


def test_countdown_vertical(plugin_config, device_config_dev):
    from plugins.countdown.countdown import Countdown

    device_config_dev.update_value("orientation", "vertical")

    with patch("plugins.countdown.countdown.datetime", wraps=datetime) as mock_dt:
        mock_dt.now.return_value = _frozen_now(2025, 6, 1)
        p = Countdown(plugin_config)
        result = p.generate_image(
            {"title": "Trip", "date": "2025-12-25"},
            device_config_dev,
        )
    assert isinstance(result, Image.Image)


def test_countdown_invalid_timezone_falls_back_to_utc(plugin_config, device_config_dev):
    """Invalid timezone must not crash countdown; get_timezone() falls back to UTC."""
    from plugins.countdown.countdown import Countdown

    device_config_dev.update_value("timezone", "Not/A_Valid_Timezone")

    with patch("plugins.countdown.countdown.datetime", wraps=datetime) as mock_dt:
        mock_dt.now.return_value = _frozen_now(2025, 6, 1)
        p = Countdown(plugin_config)
        # Should not raise ZoneInfoNotFoundError
        result = p.generate_image(
            {"title": "Fallback Test", "date": "2025-12-25"},
            device_config_dev,
        )
    assert isinstance(result, Image.Image)
