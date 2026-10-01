"""A renderer fallback must retain the launch failure diagnostic."""

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from utils.image_utils import _playwright_screenshot_html


def test_playwright_launch_failure_is_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    source = tmp_path / "render.html"
    source.write_text("<html></html>")
    with patch("playwright.sync_api.sync_playwright") as manager:
        manager.return_value.__enter__.return_value.chromium.launch.side_effect = (
            RuntimeError("launch probe failed")
        )
        with caplog.at_level(logging.WARNING, logger="utils.image_utils"):
            assert _playwright_screenshot_html(str(source), (16, 16)) is None
    assert any(
        "Playwright launch failed" in record.message and record.exc_info
        for record in caplog.records
    )
