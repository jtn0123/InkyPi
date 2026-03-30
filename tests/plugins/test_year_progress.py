# pyright: reportMissingImports=false
from datetime import datetime
from unittest.mock import patch

import pytest
import pytz
from PIL import Image


@pytest.fixture()
def plugin_config():
    return {"id": "year_progress", "class": "YearProgress", "name": "Year Progress"}


def _patch_now(year, month, day, hour=12):
    """Return a tz-aware datetime suitable for patching datetime.now."""
    tz = pytz.UTC
    return tz.localize(datetime(year, month, day, hour, 0, 0))


def test_year_progress_mid_year(plugin_config, device_config_dev):
    from plugins.year_progress.year_progress import YearProgress

    frozen = _patch_now(2025, 7, 1)
    with patch(
        "plugins.year_progress.year_progress.datetime", wraps=datetime
    ) as mock_dt:
        mock_dt.now.return_value = frozen
        p = YearProgress(plugin_config)
        result = p.generate_image({}, device_config_dev)
    assert isinstance(result, Image.Image)


def test_year_progress_start_of_year(plugin_config, device_config_dev):
    from plugins.year_progress.year_progress import YearProgress

    frozen = _patch_now(2025, 1, 2)
    with patch(
        "plugins.year_progress.year_progress.datetime", wraps=datetime
    ) as mock_dt:
        mock_dt.now.return_value = frozen
        p = YearProgress(plugin_config)
        result = p.generate_image({}, device_config_dev)
    assert isinstance(result, Image.Image)


def test_year_progress_end_of_year(plugin_config, device_config_dev):
    from plugins.year_progress.year_progress import YearProgress

    frozen = _patch_now(2025, 12, 30, 23)
    with patch(
        "plugins.year_progress.year_progress.datetime", wraps=datetime
    ) as mock_dt:
        mock_dt.now.return_value = frozen
        p = YearProgress(plugin_config)
        result = p.generate_image({}, device_config_dev)
    assert isinstance(result, Image.Image)


def test_year_progress_vertical(plugin_config, device_config_dev):
    from plugins.year_progress.year_progress import YearProgress

    device_config_dev.update_value("orientation", "vertical")

    frozen = _patch_now(2025, 6, 15)
    with patch(
        "plugins.year_progress.year_progress.datetime", wraps=datetime
    ) as mock_dt:
        mock_dt.now.return_value = frozen
        p = YearProgress(plugin_config)
        result = p.generate_image({}, device_config_dev)
    assert isinstance(result, Image.Image)
