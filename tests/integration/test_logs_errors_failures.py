# pyright: reportMissingImports=false
"""A failed log refresh keeps the logs, and Clear All keeps keyboard focus.

A 429 or 500 from the logs API blanked the viewer under a fresh "Updated"
time, and a network error left "Refreshing..." on screen for good. On the
errors page, Clear All handed focus back to its own button, which it had
just disabled, so keyboard focus fell to the page body.
"""

from __future__ import annotations

import json
import os
from typing import Any

import pytest
from playwright.sync_api import Page, Route, expect

pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_UI", "").lower() in ("1", "true"),
    reason="UI interactions skipped by env",
)

from tests.integration.browser_helpers import navigate_and_wait  # noqa: E402

_LINES = ["Nov 15 08:00:01 inkypi[1]: INFO service-1 started"]


def _serve_logs(page: Page, answers: list[str]) -> None:
    """Answer GET /api/logs with the next queued outcome (the last repeats)."""

    def answer(route: Route) -> None:
        outcome = answers.pop(0) if len(answers) > 1 else answers[0]
        if outcome == "ok":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"lines": _LINES, "count": 1, "truncated": False}),
            )
        elif outcome == "offline":
            route.abort("internetdisconnected")
        else:
            route.fulfill(
                status=int(outcome),
                content_type="application/json",
                body=json.dumps({"success": False, "error": "Too many requests"}),
            )

    page.route("**/api/logs?*", answer)


def _open_logs(page: Page, live_server: str) -> None:
    navigate_and_wait(page, live_server, "/settings")
    viewer = page.locator("#logsViewer")
    if not viewer.is_visible() and page.locator("#settingsLogsToggle").count():
        page.locator("#settingsLogsToggle").click()
    expect(viewer).to_contain_text("service-1 started")
    expect(page.locator("#logsUpdated")).to_contain_text("Updated ")


@pytest.mark.parametrize(
    ("failure", "reason"),
    [("429", "Too many requests"), ("offline", "Couldn't reach the device")],
)
def test_failed_log_refresh_keeps_the_logs_and_says_so(
    live_server: str, browser_page: Page, failure: str, reason: str
) -> None:
    page = browser_page
    _serve_logs(page, ["ok", failure])
    _open_logs(page, live_server)
    updated_at = page.locator("#logsUpdated").inner_text().removeprefix("Updated ")

    page.locator("#logsRefreshBtn").click()

    status = page.locator("#logsUpdated")
    expect(status).to_have_text(f"Refresh failed · showing logs from {updated_at}")
    expect(page.locator("#logsViewer")).to_contain_text("service-1 started")
    expect(page.locator("#logsRefreshBtn")).to_have_text("Refresh")
    expect(page.locator("#logsRefreshBtn")).to_be_enabled()
    expect(page.locator(".toast.error .toast-content")).to_contain_text(
        f"Couldn't refresh the logs: {reason}"
    )


def test_clear_all_moves_focus_to_the_empty_list_message(
    live_server: str, browser_page: Page, monkeypatch: pytest.MonkeyPatch
) -> None:
    import blueprints.errors as errors_mod

    reports: list[dict[str, Any]] = [
        {"level": "error", "message": "boom", "url": "/", "ts": ""}
    ]
    monkeypatch.setattr(errors_mod, "get_captured_reports", lambda: list(reports))
    page = browser_page
    navigate_and_wait(page, live_server, "/errors")
    expect(page.locator("#errorsCountChip")).to_have_text("1 report")

    page.locator("#errorsClearBtn").focus()
    page.keyboard.press("Enter")
    page.locator("#confirmClearErrorsBtn").focus()
    page.keyboard.press("Enter")

    empty = page.locator("#errorsEmptyState")
    expect(empty).to_be_visible()
    expect(empty).to_be_focused()
    expect(page.locator("#errorsClearBtn")).to_be_disabled()
    expect(page.locator("table[aria-label='Captured error reports']")).to_be_hidden()
    expect(page.locator("#errorsCountChip")).to_have_text("0 reports")
