"""Snapshot-test conftest.

The parent ``tests/conftest.py`` defines an autouse ``mock_screenshot``
fixture that replaces ``take_screenshot_html`` with a blank-image stub so
the rest of the suite doesn't pay the Chromium startup cost on every test.

Snapshot tests need the opposite: real Playwright Chromium rendering, so the
generated PNGs are meaningful golden files.  Overriding ``mock_screenshot``
here (same name, autouse) short-circuits the parent fixture for every test
collected under ``tests/snapshots/``.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def mock_screenshot():
    """Override the parent conftest's screenshot mock.

    Yielding without monkeypatching leaves the real ``take_screenshot_html``
    in place, so plugin ``generate_image()`` calls hit Playwright Chromium
    and produce a real rendered image — which is the whole point of the
    golden-file tests in this directory.
    """
    yield
