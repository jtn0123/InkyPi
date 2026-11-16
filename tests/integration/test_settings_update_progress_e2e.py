# pyright: reportMissingImports=false
"""The Settings page follows an update or rollback until it ends.

Every real update stops and restarts InkyPi, so the page loses the server
part-way through. These tests stand in for the device with ``page.route``:
``/settings/update_status`` answers from a scripted state the test moves
along (running, unreachable, back, finished), ``/api/version`` reports the
installed and latest versions, and ``POST /settings/update`` is answered
without starting anything. The page under test is the real Settings page
with its real scripts.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import pytest
from playwright.sync_api import Page, Route
from tests.integration.browser_helpers import navigate_and_wait

pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_UI", "").lower() in ("1", "true"),
    reason="UI interactions skipped by env",
)

_UNIT = "inkypi-update-1763280000.service"
_FAILURE = {
    "timestamp": "2026-11-16T10:00:00Z",
    "exit_code": 1,
    "last_command": "apt_install",
    "recent_journal_lines": "E: Unable to fetch some archives",
}
# Polls run every 2s and back off to 3s after failures; leave room for that.
_POLL_WAIT_MS = 15_000


def _status(
    running: bool,
    *,
    kind: str = "update",
    last_failure: dict[str, Any] | None = None,
    eligible: bool = False,
) -> dict[str, Any]:
    return {
        "running": running,
        "kind": kind if running else None,
        "unit": _UNIT if running else None,
        "started_at": 1763280000.0 if running else None,
        "last_failure": last_failure,
        "prev_version": "1.2.2",
        "rollback_eligible": eligible,
    }


def _version(current: str, latest: str) -> dict[str, Any]:
    return {
        "current": current,
        "latest": latest,
        "update_available": current != latest,
        "update_running": False,
        "release_notes": "",
        "check_succeeded": True,
        "check_error": None,
    }


class _FakeDevice:
    """Answers the update routes from state the test sets.

    While ``down`` is set the device is restarting: the first status poll
    finds nothing listening and later ones get a proxy's 503.
    """

    def __init__(self, page: Page) -> None:
        self.status = _status(False)
        self.version = _version("1.2.2", "1.3.0")
        self.down = False
        self.down_replies = 0
        self.post_reply: tuple[int, dict[str, Any]] = (
            200,
            {
                "success": True,
                "message": "Update started. Watch the Logs panel for progress.",
                "running": True,
                "unit": _UNIT,
            },
        )
        # Status the device reports once a start request arrives.
        self.status_after_post: dict[str, Any] = _status(True)
        self.posts = 0
        page.route(re.compile(r".*/settings/update_status(?:\?.*)?$"), self._on_status)
        page.route(re.compile(r".*/api/version(?:\?.*)?$"), self._on_version)
        page.route(re.compile(r".*/settings/update$"), self._on_start)

    @staticmethod
    def _json(route: Route, status: int, body: dict[str, Any]) -> None:
        route.fulfill(
            status=status, content_type="application/json", body=json.dumps(body)
        )

    def _on_status(self, route: Route) -> None:
        if not self.down:
            self._json(route, 200, self.status)
            return
        self.down_replies += 1
        if self.down_replies == 1:
            route.abort("connectionrefused")
        else:
            route.fulfill(status=503, content_type="text/html", body="Unavailable")

    def _on_version(self, route: Route) -> None:
        self._json(route, 200, self.version)

    def _on_start(self, route: Route) -> None:
        self.posts += 1
        self.status = self.status_after_post
        status, body = self.post_reply
        self._json(route, status, body)


def _open_update_panel(page: Page, live_server: str) -> None:
    navigate_and_wait(page, live_server, "/settings")
    page.locator('[data-settings-tab="maintenance"]').first.click()
    page.wait_for_selector("#checkUpdatesBtn", state="visible", timeout=5000)


def _wait_for_progress(page: Page, state: str, text: str) -> str:
    """Wait until the progress line is in ``state`` and shows ``text``."""
    page.wait_for_function(
        """([state, text]) => {
          const box = document.getElementById("updateProgress");
          const line = document.getElementById("updateProgressText");
          return !!box && !box.hidden && box.dataset.state === state
            && !!line && line.textContent.includes(text);
        }""",
        arg=[state, text],
        timeout=_POLL_WAIT_MS,
    )
    return page.locator("#updateProgressText").inner_text().strip()


def _panel_busy(page: Page) -> str | None:
    return page.locator("#updatePanel").get_attribute("aria-busy")


def _check_for_updates(page: Page) -> None:
    page.locator("#checkUpdatesBtn").click()
    page.wait_for_selector("#startUpdateBtn:not([disabled])", timeout=5000)


def test_page_follows_a_running_update_through_the_restart(
    live_server: str, browser_page: Page
) -> None:
    page = browser_page
    device = _FakeDevice(page)
    device.status = _status(True)

    # The update was already running when the page loaded.
    _open_update_panel(page, live_server)
    _wait_for_progress(page, "running", "Updating…")
    assert page.locator("#startUpdateBtn").is_disabled()
    assert _panel_busy(page) == "true"

    # The page's own version check finds 1.3.0, but Update now stays
    # disabled while the update runs.
    page.wait_for_function(
        "() => (document.getElementById('latestVersion')?.textContent || '')"
        ".includes('1.3.0')",
        timeout=_POLL_WAIT_MS,
    )
    assert page.locator("#startUpdateBtn").is_disabled()

    # InkyPi stops: nothing listens, then a proxy answers 503.
    device.down = True
    _wait_for_progress(page, "running", "Restarting… waiting for InkyPi to come back.")
    # The page keeps asking: wait for its retry to get the 503.
    deadline = time.monotonic() + _POLL_WAIT_MS / 1000
    while device.down_replies < 2 and time.monotonic() < deadline:
        page.wait_for_timeout(50)
    assert device.down_replies >= 2, "the page stopped asking while InkyPi was down"
    _wait_for_progress(page, "running", "Restarting…")
    assert page.locator("#startUpdateBtn").is_disabled()

    # InkyPi is back and update.sh is still checking the new version.
    device.down = False
    _wait_for_progress(page, "running", "InkyPi is back")

    # The update finishes: the page says so and shows the new version.
    device.version = _version("1.3.0", "1.3.0")
    device.status = _status(False)
    text = _wait_for_progress(page, "success", "now running v1.3.0")
    assert text == "Update finished. InkyPi is now running v1.3.0."
    assert page.locator("#currentVersion").inner_text().strip() == "1.3.0"
    assert page.locator("#updateReloadBtn").is_visible()
    assert _panel_busy(page) == "false"
    assert page.locator("#updateFailureBanner").is_hidden()
    # Nothing newer to install.
    page.wait_for_selector("#startUpdateBtn[disabled]", timeout=5000)


def test_failed_update_shows_its_reason_and_offers_the_rollback(
    live_server: str, browser_page: Page
) -> None:
    page = browser_page
    device = _FakeDevice(page)

    _open_update_panel(page, live_server)
    _check_for_updates(page)
    assert page.locator("#updateProgress").is_hidden()

    page.locator("#startUpdateBtn").click()
    _wait_for_progress(page, "running", "Updating…")
    assert device.posts == 1
    assert page.locator("#startUpdateBtn").is_disabled()

    device.status = _status(False, last_failure=_FAILURE, eligible=True)
    text = _wait_for_progress(page, "failure", "Update failed")
    assert text == "Update failed at step: apt_install (exit 1). The details are below."
    assert page.locator("#updateFailureBanner").is_visible()
    assert "apt_install" in page.locator("#updateFailureStep").inner_text()
    rollback = page.locator("#rollbackUpdateBtn")
    assert rollback.is_visible()
    assert rollback.is_enabled()
    assert page.locator("#rollbackTargetVersion").inner_text().strip() == "1.2.2"
    assert page.locator("#updateReloadBtn").is_visible()
    assert _panel_busy(page) == "false"


def test_refused_start_follows_the_run_already_going(
    live_server: str, browser_page: Page
) -> None:
    page = browser_page
    device = _FakeDevice(page)
    device.post_reply = (
        409,
        {
            "success": False,
            "error": "An update or rollback is already in progress.",
            "code": "already_running",
            "running": True,
            "unit": _UNIT,
        },
    )
    device.status_after_post = _status(True, kind="rollback")

    _open_update_panel(page, live_server)
    _check_for_updates(page)
    page.locator("#startUpdateBtn").click()

    # The refusal is shown, and the page follows the rollback that is going.
    _wait_for_progress(page, "running", "Rolling back…")
    assert page.locator("#startUpdateBtn").is_disabled()

    device.status = _status(False)
    text = _wait_for_progress(page, "success", "Rollback finished.")
    assert text.startswith("Rollback finished.")
    assert _panel_busy(page) == "false"


def test_sidebar_quick_update_is_followed_on_the_settings_page(
    live_server: str, browser_page: Page
) -> None:
    page = browser_page
    device = _FakeDevice(page)

    _open_update_panel(page, live_server)
    page.wait_for_selector("#sidebarUpdateBtn:not([hidden])", timeout=5000)
    page.locator("#sidebarUpdateBtn").click()
    page.wait_for_function(
        """() => {
          const m = document.getElementById('quickUpdateModal');
          return m && getComputedStyle(m).display === 'block';
        }""",
        timeout=3000,
    )
    page.locator("#quickUpdateStartBtn").click()

    _wait_for_progress(page, "running", "Updating…")
    assert device.posts == 1
    assert page.locator("#startUpdateBtn").is_disabled()

    device.version = _version("1.3.0", "1.3.0")
    device.status = _status(False)
    _wait_for_progress(page, "success", "Update finished.")
    assert _panel_busy(page) == "false"
