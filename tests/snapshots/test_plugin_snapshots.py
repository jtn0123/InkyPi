# pyright: reportMissingImports=false
"""Golden-file snapshot tests for deterministic plugin outputs.

Each test freezes time (and any other non-deterministic inputs) then compares
the SHA-256 digest of the rendered PNG against a stored baseline.

Browser requirement
-------------------
Plugins under test render HTML→PNG via Playwright/Chromium.  Without the
browser installed, ``_screenshot_fallback()`` in ``base_plugin.py`` returns a
blank white canvas — every plugin produces the same bytes and the test
degrades into a useless no-op.  To prevent that, these tests only run when
``REQUIRE_BROWSER_SMOKE=1`` is set (same gate the browser-smoke CI job uses).
In the main ``Tests (pytest)`` CI job the files are still collected but
skip cleanly because the env var is absent.

The parent ``tests/conftest.py`` also has an autouse ``mock_screenshot``
fixture that stubs ``take_screenshot_html`` into a blank canvas so the rest
of the suite doesn't pay the Chromium startup cost.  A sibling
``tests/snapshots/conftest.py`` overrides that fixture (with the same name +
``autouse=True``) so real Chromium rendering happens here.

Updating baselines
------------------
Run ``python scripts/update_snapshots.py`` or set
``SNAPSHOT_UPDATE=1 REQUIRE_BROWSER_SMOKE=1`` before running pytest.  See
``tests/snapshots/README.md`` for the full workflow (including the docker
one-liner that matches the CI environment).
"""

import os
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from PIL import Image

from tests.snapshots.snapshot_helper import assert_image_snapshot

pytestmark = pytest.mark.skipif(
    os.getenv("REQUIRE_BROWSER_SMOKE", "").lower() not in ("1", "true"),
    reason=(
        "Plugin snapshot tests render HTML via Playwright Chromium. "
        "Set REQUIRE_BROWSER_SMOKE=1 to run them (see tests/snapshots/README.md)."
    ),
)

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
