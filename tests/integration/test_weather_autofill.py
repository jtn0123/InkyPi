# pyright: reportMissingImports=false
"""Weather plugin settings page browser tests."""

from __future__ import annotations

import os

import pytest
from tests.integration.browser_helpers import navigate_and_wait

pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_UI", "").lower() in ("1", "true"),
    reason="UI interactions skipped by env",
)


def test_weather_settings_has_location_fields(live_server: str) -> None:
    """Weather plugin page has latitude and longitude input fields."""
    pytest.importorskip("playwright.sync_api", reason="playwright not available")

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            collector = navigate_and_wait(page, live_server, "/plugin/weather")

            # Verify latitude and longitude fields exist
            assert page.locator("#latitude").count() == 1
            assert page.locator("#longitude").count() == 1

            collector.assert_no_errors(name="weather_location_fields")
        finally:
            browser.close()


def test_weather_settings_has_map_button(live_server: str) -> None:
    """Weather plugin page has an Open Map button for location selection."""
    pytest.importorskip("playwright.sync_api", reason="playwright not available")

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            collector = navigate_and_wait(page, live_server, "/plugin/weather")

            # Open Map button should exist
            open_map = page.locator("#openMap")
            assert open_map.count() == 1

            collector.assert_no_errors(name="weather_map_button")
        finally:
            browser.close()


def test_weather_settings_form_has_units_and_provider(live_server: str) -> None:
    """Weather plugin page has units and provider selection fields."""
    pytest.importorskip("playwright.sync_api", reason="playwright not available")

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            collector = navigate_and_wait(page, live_server, "/plugin/weather")

            # Settings form should have units select
            form = page.locator("#settingsForm")
            assert form.count() == 1
            assert page.locator("#units").count() == 1

            collector.assert_no_errors(name="weather_form_fields")
        finally:
            browser.close()


def test_weather_title_section_hidden_when_all_fields_hidden(live_server: str) -> None:
    """The "Title" section only holds OpenWeatherMap-only fields. Under the
    default Open-Meteo provider it must not render as an empty heading-only
    card, and it must reappear when the provider switches."""
    pytest.importorskip("playwright.sync_api", reason="playwright not available")

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            collector = navigate_and_wait(page, live_server, "/plugin/weather")

            title_section = page.locator(".schema-section").filter(
                has=page.locator(".settings-card-title", has_text="Title")
            )
            assert title_section.count() == 1
            page.select_option("select[name='weatherProvider']", "OpenMeteo")
            assert title_section.is_hidden()

            page.select_option("select[name='weatherProvider']", "OpenWeatherMap")
            assert title_section.is_visible()

            page.select_option("select[name='weatherProvider']", "OpenMeteo")
            assert title_section.is_hidden()

            collector.assert_no_errors(name="weather_title_section_visibility")
        finally:
            browser.close()
