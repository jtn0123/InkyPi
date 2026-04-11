# pyright: reportMissingImports=false
"""Golden-file snapshot tests for deterministic plugin outputs.

Each test freezes time (and any other non-deterministic inputs) then compares
the SHA-256 digest of the rendered PNG against a stored baseline.

Updating baselines
------------------
Run ``python scripts/update_snapshots.py`` or set SNAPSHOT_UPDATE=1 before
running pytest.  See tests/snapshots/README.md for the full workflow.
"""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from PIL import Image

from tests.snapshots.snapshot_helper import assert_image_snapshot

# ---------------------------------------------------------------------------
# year_progress
# ---------------------------------------------------------------------------


@pytest.fixture()
def year_progress_plugin_config():
    return {"id": "year_progress", "class": "YearProgress", "name": "Year Progress"}


def test_snapshot_year_progress_mid_year(
    year_progress_plugin_config, device_config_dev
):
    """Snapshot: year_progress at 2025-07-01 12:00 UTC (horizontal)."""
    from plugins.year_progress.year_progress import YearProgress

    frozen = datetime(2025, 7, 1, 12, 0, 0, tzinfo=UTC)
    with patch(
        "plugins.year_progress.year_progress.datetime", wraps=datetime
    ) as mock_dt:
        mock_dt.now.return_value = frozen
        plugin = YearProgress(year_progress_plugin_config)
        result = plugin.generate_image({}, device_config_dev)

    assert isinstance(result, Image.Image)
    assert_image_snapshot(result, "year_progress", "mid_year_horizontal")


def test_snapshot_year_progress_start_of_year(
    year_progress_plugin_config, device_config_dev
):
    """Snapshot: year_progress at 2025-01-02 12:00 UTC (horizontal)."""
    from plugins.year_progress.year_progress import YearProgress

    frozen = datetime(2025, 1, 2, 12, 0, 0, tzinfo=UTC)
    with patch(
        "plugins.year_progress.year_progress.datetime", wraps=datetime
    ) as mock_dt:
        mock_dt.now.return_value = frozen
        plugin = YearProgress(year_progress_plugin_config)
        result = plugin.generate_image({}, device_config_dev)

    assert isinstance(result, Image.Image)
    assert_image_snapshot(result, "year_progress", "start_of_year_horizontal")


# ---------------------------------------------------------------------------
# countdown
# ---------------------------------------------------------------------------


@pytest.fixture()
def countdown_plugin_config():
    return {"id": "countdown", "class": "Countdown", "name": "Countdown"}


def test_snapshot_countdown_future(countdown_plugin_config, device_config_dev):
    """Snapshot: countdown to 2025-12-25 from 2025-06-01 (horizontal)."""
    from plugins.countdown.countdown import Countdown

    frozen = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
    with patch("plugins.countdown.countdown.datetime", wraps=datetime) as mock_dt:
        mock_dt.now.return_value = frozen
        plugin = Countdown(countdown_plugin_config)
        result = plugin.generate_image(
            {"title": "Christmas", "date": "2025-12-25"},
            device_config_dev,
        )

    assert isinstance(result, Image.Image)
    assert_image_snapshot(result, "countdown", "future_horizontal")
