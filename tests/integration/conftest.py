# pyright: reportMissingImports=false
"""Shared fixtures for Playwright-based integration tests."""

from __future__ import annotations

import pytest


@pytest.fixture()
def browser_page():
    """Desktop-sized Playwright page (1280x900). Closes browser on teardown."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        yield page
        browser.close()


@pytest.fixture()
def mobile_page():
    """Mobile-sized Playwright page (360x800). Closes browser on teardown."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 360, "height": 800})
        yield page
        browser.close()
