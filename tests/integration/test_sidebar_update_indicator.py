# pyright: reportMissingImports=false
"""DOM-level verification of the sidebar update indicator.

The sidebar brand row carries a tiny download chip that unhides when
``/api/version`` reports an upgrade. Clicking it opens the shared quick
update confirm modal rendered in base.html. This test covers that flow
end-to-end (indicator visible, modal populated, confirm POST fires) so
the one-click update path the user asked for can't regress silently.
"""

from __future__ import annotations

import json
import os

import pytest
from tests.integration.browser_helpers import navigate_and_wait

pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_UI", "").lower() in ("1", "true"),
    reason="UI interactions skipped by env",
)


def _stub_api_version(page, payload: dict) -> None:
    def handler(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(payload),
        )

    page.route("**/api/version", handler)


def _stub_update_post(page, response: dict, status: int = 200) -> list[dict]:
    """Stub POST /settings/update and record each call for assertions."""
    calls: list[dict] = []

    def handler(route):
        request = route.request
        calls.append({"method": request.method, "url": request.url})
        route.fulfill(
            status=status,
            content_type="application/json",
            body=json.dumps(response),
        )

    page.route("**/settings/update", handler)
    return calls


def _wait_for_indicator_check(page):
    """Wait until update_indicator.js finishes its /api/version round trip."""
    page.wait_for_function(
        """() => {
          const raw = sessionStorage.getItem('inkypi-update-check');
          if (!raw) return false;
          try {
            const parsed = JSON.parse(raw);
            return parsed && parsed.data && typeof parsed.data.update_available === 'boolean';
          } catch (e) { return false; }
        }""",
        timeout=5000,
    )


def test_sidebar_indicator_shows_when_update_available(live_server, browser_page):
    """update_available=true unhides the sidebar button with correct labels."""
    page = browser_page
    _stub_api_version(
        page,
        {
            "current": "0.64.1",
            "latest": "0.65.0",
            "update_available": True,
            "update_running": False,
            "release_notes": "# v0.65.0\n\n- New stuff",
        },
    )
    navigate_and_wait(page, live_server, "/")
    _wait_for_indicator_check(page)
    page.wait_for_selector("#sidebarUpdateBtn:not([hidden])", timeout=5000)

    state = page.evaluate("""() => {
          const btn = document.getElementById('sidebarUpdateBtn');
          return {
            hidden: btn.hidden,
            title: btn.getAttribute('title'),
            ariaLabel: btn.getAttribute('aria-label'),
            latest: btn.dataset.latest,
            current: btn.dataset.current,
            hasDot: !!btn.querySelector('.sidebar-update-dot'),
          };
        }""")
    assert state["hidden"] is False
    assert state["title"] == "Update available: v0.65.0"
    assert state["ariaLabel"] == "Update available: v0.65.0"
    assert state["latest"] == "0.65.0"
    assert state["current"] == "0.64.1"
    assert state["hasDot"] is True


def test_sidebar_indicator_hidden_when_up_to_date(live_server, browser_page):
    """update_available=false keeps the sidebar button hidden."""
    page = browser_page
    _stub_api_version(
        page,
        {
            "current": "0.64.1",
            "latest": "0.64.1",
            "update_available": False,
            "update_running": False,
            "release_notes": "# v0.64.1\n\n- Stabilize\n",
        },
    )
    navigate_and_wait(page, live_server, "/")
    _wait_for_indicator_check(page)

    hidden = page.evaluate("() => document.getElementById('sidebarUpdateBtn').hidden")
    assert hidden is True


def test_sidebar_indicator_click_opens_modal_with_versions(live_server, browser_page):
    """Clicking the button opens the quick-update modal with populated versions."""
    page = browser_page
    _stub_api_version(
        page,
        {
            "current": "0.64.1",
            "latest": "0.65.0",
            "update_available": True,
            "update_running": False,
            "release_notes": "",
        },
    )
    navigate_and_wait(page, live_server, "/")
    _wait_for_indicator_check(page)
    page.wait_for_selector("#sidebarUpdateBtn:not([hidden])", timeout=5000)

    page.locator("#sidebarUpdateBtn").click()
    page.wait_for_function(
        """() => {
          const m = document.getElementById('quickUpdateModal');
          return m && !m.hidden && getComputedStyle(m).display !== 'none';
        }""",
        timeout=3000,
    )

    state = page.evaluate("""() => ({
          display: getComputedStyle(document.getElementById('quickUpdateModal')).display,
          latest: (document.getElementById('quickUpdateLatest').textContent || '').trim(),
          current: (document.getElementById('quickUpdateCurrent').textContent || '').trim(),
          detailsHref: document.getElementById('quickUpdateDetailsLink').getAttribute('href'),
          hasStart: !!document.getElementById('quickUpdateStartBtn'),
          hasCancel: !!document.getElementById('quickUpdateCancelBtn'),
        })""")
    assert state["display"] == "block"
    assert state["latest"] == "v0.65.0"
    assert state["current"] == "v0.64.1"
    assert "section-software-update" in state["detailsHref"]
    assert state["hasStart"] is True
    assert state["hasCancel"] is True


def test_sidebar_indicator_confirm_posts_update(live_server, browser_page):
    """Confirming in the modal POSTs /settings/update and closes the modal."""
    page = browser_page
    _stub_api_version(
        page,
        {
            "current": "0.64.1",
            "latest": "0.65.0",
            "update_available": True,
            "update_running": False,
            "release_notes": "",
        },
    )
    calls = _stub_update_post(page, {"success": True, "message": "Update started."})
    navigate_and_wait(page, live_server, "/")
    _wait_for_indicator_check(page)
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
    page.wait_for_function(
        """() => {
          const m = document.getElementById('quickUpdateModal');
          return m && getComputedStyle(m).display === 'none';
        }""",
        timeout=5000,
    )

    assert len(calls) == 1
    assert calls[0]["method"] == "POST"
    assert calls[0]["url"].endswith("/settings/update")


def test_settings_hash_activates_update_tab(live_server, browser_page):
    """Landing on /settings#section-software-update should auto-activate
    the Updates (maintenance) panel, not leave the user on the default
    Device tab. This is what the quick-update modal's "See release notes"
    link relies on to land in the right place."""
    page = browser_page
    _stub_api_version(
        page,
        {
            "current": "0.64.1",
            "latest": "0.64.1",
            "update_available": False,
            "update_running": False,
            "release_notes": None,
        },
    )
    navigate_and_wait(page, live_server, "/settings#section-software-update")
    page.wait_for_function(
        """() => {
          const panel = document.querySelector('[data-settings-panel="maintenance"]');
          return !!panel && panel.classList.contains('active');
        }""",
        timeout=5000,
    )
    active = page.evaluate(
        "() => document.querySelector('[data-settings-panel].active').dataset.settingsPanel"
    )
    assert active == "maintenance"


def test_sidebar_indicator_cancel_closes_modal_without_post(live_server, browser_page):
    """Cancel dismisses the modal and must not POST /settings/update."""
    page = browser_page
    _stub_api_version(
        page,
        {
            "current": "0.64.1",
            "latest": "0.65.0",
            "update_available": True,
            "update_running": False,
            "release_notes": "",
        },
    )
    calls = _stub_update_post(page, {"success": True})
    navigate_and_wait(page, live_server, "/")
    _wait_for_indicator_check(page)
    page.wait_for_selector("#sidebarUpdateBtn:not([hidden])", timeout=5000)
    page.locator("#sidebarUpdateBtn").click()
    page.wait_for_function(
        """() => getComputedStyle(document.getElementById('quickUpdateModal')).display === 'block'""",
        timeout=3000,
    )
    page.locator("#quickUpdateCancelBtn").click()
    page.wait_for_function(
        """() => getComputedStyle(document.getElementById('quickUpdateModal')).display === 'none'""",
        timeout=3000,
    )
    assert calls == []
