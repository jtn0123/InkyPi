# pyright: reportMissingImports=false
from datetime import datetime
from unittest.mock import patch

import pytz
import pytest
from PIL import Image


@pytest.fixture()
def plugin_config():
    return {"id": "countdown", "class": "Countdown", "name": "Countdown"}


def _frozen_now(year, month, day):
    tz = pytz.UTC
    return tz.localize(datetime(year, month, day, 12, 0, 0))


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


def test_countdown_missing_date(plugin_config, device_config_dev):
    from plugins.countdown.countdown import Countdown

    p = Countdown(plugin_config)
    with pytest.raises(RuntimeError, match="Date is required"):
        p.generate_image({"title": "No Date"}, device_config_dev)


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
