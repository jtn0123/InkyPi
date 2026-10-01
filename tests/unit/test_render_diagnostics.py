"""Renderer diagnostics preserve failures without disrupting valid screenshots."""

import logging
from collections.abc import Iterator
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from utils.image_utils import _playwright_screenshot_html


@pytest.fixture
def render_browser() -> Iterator[MagicMock]:
    """Supply a browser that returns an actual decodable PNG."""
    with patch("playwright.sync_api.sync_playwright") as manager:
        browser = (
            manager.return_value.__enter__.return_value.chromium.launch.return_value
        )
        browser.version = "154.0.test"
        output = BytesIO()
        Image.new("RGB", (16, 16), (12, 34, 56)).save(output, format="PNG")
        browser.new_page.return_value.screenshot.return_value = output.getvalue()
        yield browser


@pytest.mark.parametrize("level", [logging.INFO, logging.DEBUG])
def test_success_records_debug_state_only_when_enabled(
    render_browser: MagicMock, caplog: pytest.LogCaptureFixture, level: int
) -> None:
    page = render_browser.new_page.return_value
    page.evaluate.side_effect = [None, {"status": "loaded", "faces": []}]
    with caplog.at_level(level, logger="utils.image_utils"):
        image = _playwright_screenshot_html("/render.html", (16, 16))
    assert image is not None
    assert image.size == (16, 16)
    assert image.getpixel((0, 0)) == (12, 34, 56)
    assert page.evaluate.call_count == (2 if level == logging.DEBUG else 1)
    if level == logging.DEBUG:
        assert "Playwright Chromium 154.0.test" in caplog.text
        assert "font state: {'status': 'loaded', 'faces': []}" in caplog.text
    else:
        assert not caplog.records
    render_browser.close.assert_called_once()


def test_font_diagnostic_failure_preserves_render(
    render_browser: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    page = render_browser.new_page.return_value
    page.evaluate.side_effect = [None, RuntimeError("font probe failed")]
    with caplog.at_level(logging.DEBUG, logger="utils.image_utils"):
        image = _playwright_screenshot_html("/render.html", (16, 16))
    assert image is not None
    assert image.getpixel((0, 0)) == (12, 34, 56)
    assert any(
        "font diagnostics failed" in record.message and record.exc_info
        for record in caplog.records
    )
    render_browser.close.assert_called_once()


@pytest.mark.parametrize("operation", ["wait_for_load_state", "evaluate"])
def test_resource_failure_keeps_screenshot_and_exception(
    render_browser: MagicMock, caplog: pytest.LogCaptureFixture, operation: str
) -> None:
    page = render_browser.new_page.return_value
    getattr(page, operation).side_effect = RuntimeError("resource probe failed")
    with caplog.at_level(logging.WARNING, logger="utils.image_utils"):
        image = _playwright_screenshot_html("/render.html", (16, 16))
    assert image is not None
    assert image.size == (16, 16)
    assert any(
        "resource readiness failed" in record.message and record.exc_info
        for record in caplog.records
    )
    render_browser.close.assert_called_once()


def test_screenshot_failure_logs_and_closes_browser(
    render_browser: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    render_browser.new_page.return_value.screenshot.side_effect = RuntimeError(
        "screenshot probe failed"
    )
    with caplog.at_level(logging.WARNING, logger="utils.image_utils"):
        assert _playwright_screenshot_html("/render.html", (16, 16)) is None
    assert any(
        "local HTML render failed" in record.message and record.exc_info
        for record in caplog.records
    )
    render_browser.close.assert_called_once()


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
