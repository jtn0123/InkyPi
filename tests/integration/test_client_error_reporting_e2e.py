# pyright: reportMissingImports=false
"""Browser error reports must reach the server with CSRF enforced.

The shared integration app skips CSRF validation, so these tests switch the
production middleware back on. Before C7, the error reporter and the console
log reporter's unload flush both used ``navigator.sendBeacon``. A beacon
cannot carry the ``X-CSRFToken`` header, so the server rejected every one of
those reports with 403 and the browser never noticed.
"""

from __future__ import annotations

import os
import time
from typing import Any

import pytest
from flask import Flask
from playwright.sync_api import Page, Response

pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_UI", "").lower() in ("1", "true"),
    reason="UI interactions skipped by env",
)

_PAGE = "/plugins"


@pytest.fixture()
def csrf_enforced(flask_app: Flask) -> Flask:
    """Register the production CSRF check before the live server serves anything."""
    from app_setup.security_middleware import setup_csrf_protection

    setup_csrf_protection(flask_app)
    return flask_app


def _report_body(response: Response) -> dict[str, Any]:
    body = response.request.post_data_json
    assert isinstance(body, dict), f"report body is not a JSON object: {body!r}"
    return body


def _is_error_report(response: Response) -> bool:
    path = response.url.split("?")[0]
    return response.request.method == "POST" and path.endswith("/api/client-error")


def test_uncaught_error_report_is_accepted(
    csrf_enforced: Flask, live_server: str, browser_page: Page
) -> None:
    page = browser_page
    page.goto(f"{live_server}{_PAGE}", wait_until="load")

    with page.expect_response(_is_error_report, timeout=5000) as info:
        page.evaluate("setTimeout(() => { throw new Error('c7 uncaught probe'); }, 0)")

    response = info.value
    assert response.status == 204, f"report rejected with {response.status}"
    assert "c7 uncaught probe" in _report_body(response)["message"]


def test_unhandled_rejection_report_is_accepted(
    csrf_enforced: Flask, live_server: str, browser_page: Page
) -> None:
    page = browser_page
    page.goto(f"{live_server}{_PAGE}", wait_until="load")

    with page.expect_response(_is_error_report, timeout=5000) as info:
        page.evaluate("() => { Promise.reject(new Error('c7 rejection probe')); }")

    response = info.value
    assert response.status == 204, f"report rejected with {response.status}"
    body = _report_body(response)
    assert body["message"] == "c7 rejection probe"
    assert "c7 rejection probe" in body["stack"]


def test_each_error_is_reported_once(
    csrf_enforced: Flask, live_server: str, browser_page: Page
) -> None:
    """Only one reporter listens now, so one error makes one report."""
    page = browser_page
    reports: list[str] = []
    page.on(
        "request",
        lambda request: (
            reports.append(request.url)
            if request.method == "POST" and "client" in request.url
            else None
        ),
    )
    page.goto(f"{live_server}{_PAGE}", wait_until="load")

    with page.expect_response(_is_error_report, timeout=5000):
        page.evaluate("setTimeout(() => { throw new Error('c7 single probe'); }, 0)")
    # Both old listeners fired in the same task; one more round trip makes
    # sure Playwright has delivered every request event from that task.
    page.evaluate("1")

    assert [url.split("?")[0].removeprefix(live_server) for url in reports] == [
        "/api/client-error"
    ]


@pytest.mark.expected_client_logs(r"c7 unload probe")
def test_console_error_flushed_on_pagehide_reaches_server(
    csrf_enforced: Flask, live_server: str, browser_page: Page
) -> None:
    """The unload flush must carry the CSRF header like the timed flush does."""
    from blueprints.client_log import get_captured_reports

    page = browser_page
    page.goto(f"{live_server}{_PAGE}", wait_until="load")

    # Fire pagehide inside the 500 ms coalesce window, so the unload path
    # (not the timer) sends the batch.
    page.evaluate("""() => {
            console.error('c7 unload probe');
            globalThis.dispatchEvent(new PageTransitionEvent('pagehide'));
        }""")

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        messages = [str(r.get("message", "")) for r in get_captured_reports()]
        if any("c7 unload probe" in m for m in messages):
            return
        page.wait_for_timeout(50)
    pytest.fail("console.error flushed on pagehide never reached /api/client-log")
