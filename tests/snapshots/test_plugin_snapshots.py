# pyright: reportMissingImports=false
"""Golden-file snapshot tests for deterministic plugin outputs.

Each test freezes time (and any other non-deterministic inputs) then compares
the SHA-256 digest of the rendered PNG against a stored baseline.

Browser requirement
-------------------
Some plugins render HTML->PNG via Playwright/Chromium and are gated behind
``REQUIRE_BROWSER_SMOKE=1``.  Others (clock, image_upload, image_folder)
render directly via PIL and work without a browser -- those tests always run.

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
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from tests.snapshots.snapshot_helper import assert_image_snapshot

_requires_browser = pytest.mark.skipif(
    os.getenv("REQUIRE_BROWSER_SMOKE", "").lower() not in ("1", "true"),
    reason=(
        "Plugin snapshot tests render HTML via Playwright Chromium. "
        "Set REQUIRE_BROWSER_SMOKE=1 to run them (see tests/snapshots/README.md)."
    ),
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture()
def fixture_png(tmp_path):
    """Create a deterministic 200x200 red/blue test PNG and return its path."""
    img = Image.new("RGB", (200, 200), (255, 0, 0))
    # Add a blue quadrant so the image has visible structure
    for x in range(100):
        for y in range(100):
            img.putpixel((x + 100, y + 100), (0, 0, 255))
    path = tmp_path / "fixture.png"
    img.save(path, format="PNG")
    return str(path)


# ---------------------------------------------------------------------------
# year_progress
# ---------------------------------------------------------------------------


@pytest.fixture()
def year_progress_plugin_config():
    return {"id": "year_progress", "class": "YearProgress", "name": "Year Progress"}


@_requires_browser
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


@_requires_browser
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


@_requires_browser
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


# ---------------------------------------------------------------------------
# clock (PIL-only rendering — no browser required)
# ---------------------------------------------------------------------------


@pytest.fixture()
def clock_plugin_config():
    return {"id": "clock", "class": "Clock", "name": "Clock"}


def test_snapshot_clock_digital(clock_plugin_config, device_config_dev):
    """Snapshot: clock Digital face at 14:30 UTC."""
    from plugins.clock.clock import Clock

    frozen = datetime(2025, 7, 1, 14, 30, 0, tzinfo=UTC)
    with patch("plugins.clock.clock.datetime", wraps=datetime) as mock_dt:
        mock_dt.now.return_value = frozen
        plugin = Clock(clock_plugin_config)
        result = plugin.generate_image(
            {
                "selectedClockFace": "Digital Clock",
                "primaryColor": "#ffffff",
                "secondaryColor": "#000000",
            },
            device_config_dev,
        )

    assert isinstance(result, Image.Image)
    assert_image_snapshot(result, "clock", "digital_1430")


def test_snapshot_clock_word(clock_plugin_config, device_config_dev):
    """Snapshot: clock Word face at 10:15 UTC."""
    from plugins.clock.clock import Clock

    frozen = datetime(2025, 7, 1, 10, 15, 0, tzinfo=UTC)
    with patch("plugins.clock.clock.datetime", wraps=datetime) as mock_dt:
        mock_dt.now.return_value = frozen
        plugin = Clock(clock_plugin_config)
        result = plugin.generate_image(
            {
                "selectedClockFace": "Word Clock",
                "primaryColor": "#000000",
                "secondaryColor": "#ffffff",
            },
            device_config_dev,
        )

    assert isinstance(result, Image.Image)
    assert_image_snapshot(result, "clock", "word_1015")


# ---------------------------------------------------------------------------
# todo_list (HTML rendering — browser required)
# ---------------------------------------------------------------------------


@pytest.fixture()
def todo_list_plugin_config():
    return {"id": "todo_list", "class": "TodoList", "name": "Todo List"}


@_requires_browser
def test_snapshot_todo_list(todo_list_plugin_config, device_config_dev):
    """Snapshot: todo_list with two lists, disc style."""
    from plugins.todo_list.todo_list import TodoList

    plugin = TodoList(todo_list_plugin_config)
    result = plugin.generate_image(
        {
            "title": "My Tasks",
            "listStyle": "disc",
            "fontSize": "normal",
            "list-title[]": ["Groceries", "Chores"],
            "list[]": ["Milk\nEggs\nBread", "Vacuum\nLaundry"],
        },
        device_config_dev,
    )

    assert isinstance(result, Image.Image)
    assert_image_snapshot(result, "todo_list", "two_lists_disc")


# ---------------------------------------------------------------------------
# image_upload (PIL-only — no browser required)
# ---------------------------------------------------------------------------


@pytest.fixture()
def image_upload_plugin_config():
    return {"id": "image_upload", "class": "ImageUpload", "name": "Image Upload"}


def test_snapshot_image_upload_pad_color(
    image_upload_plugin_config, device_config_dev, fixture_png
):
    """Snapshot: image_upload with color padding on a fixture PNG."""
    from plugins.image_upload.image_upload import ImageUpload

    plugin = ImageUpload(image_upload_plugin_config)
    with patch(
        "plugins.image_upload.image_upload.validate_file_path",
        side_effect=lambda p, _base: p,
    ):
        result = plugin.generate_image(
            {
                "imageFiles[]": [fixture_png],
                "image_index": 0,
                "padImage": "true",
                "backgroundOption": "color",
                "backgroundColor": "#ffffff",
                "randomize": "false",
            },
            device_config_dev,
        )

    assert isinstance(result, Image.Image)
    assert_image_snapshot(result, "image_upload", "pad_color_white")


# ---------------------------------------------------------------------------
# image_folder (PIL-only — no browser required)
# ---------------------------------------------------------------------------


@pytest.fixture()
def image_folder_plugin_config():
    return {"id": "image_folder", "class": "ImageFolder", "name": "Image Folder"}


def test_snapshot_image_folder_fit(
    image_folder_plugin_config, device_config_dev, fixture_png, tmp_path
):
    """Snapshot: image_folder with crop-to-fit on a fixture PNG."""
    from plugins.image_folder.image_folder import ImageFolder

    plugin = ImageFolder(image_folder_plugin_config)
    with (
        patch(
            "plugins.image_folder.image_folder.list_files_in_folder",
            return_value=[fixture_png],
        ),
        patch(
            "plugins.image_folder.image_folder.random.choice",
            return_value=fixture_png,
        ),
    ):
        result = plugin.generate_image(
            {
                "folder_path": str(tmp_path),
                "padImage": "false",
                "backgroundOption": "blur",
            },
            device_config_dev,
        )

    assert isinstance(result, Image.Image)
    assert_image_snapshot(result, "image_folder", "fit_fixture")
