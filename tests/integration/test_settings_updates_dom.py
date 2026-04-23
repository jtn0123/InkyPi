# pyright: reportMissingImports=false
"""DOM-level verification of the Settings → Updates tab.

Covers the rendering path the user reported as broken in 2026-04-22:
release notes appeared as raw markdown, the "· v<latest>" suffix never
populated, and the "What's new" button stayed visible when the device
was already up to date. Each scenario stubs ``/api/version`` so the
assertions don't depend on the live GitHub API, and the JS-only
``renderReleaseNotesHTML`` helper is also exercised directly as a unit
check of the markdown→HTML conversion.
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
    """Route /api/version to return a known JSON payload."""

    def handler(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(payload),
        )

    page.route("**/api/version", handler)


def _open_maintenance_tab(page):
    page.locator('[data-settings-tab="maintenance"]').first.click()
    page.wait_for_function(
        """() => {
          const panel = document.querySelector('[data-settings-panel="maintenance"]');
          return !!panel && panel.classList.contains("active");
        }""",
        timeout=8000,
    )
    page.wait_for_selector("#checkUpdatesBtn", state="visible", timeout=5000)


def _click_check_and_wait(page):
    page.locator("#checkUpdatesBtn").click()
    # Wait until the check button leaves its "Checking..." state —
    # actions.js swaps the `.btn-label` text back and re-enables the
    # button only after fetchVersionData resolves.
    page.wait_for_function(
        """() => {
          const btn = document.getElementById("checkUpdatesBtn");
          const label = btn && btn.querySelector(".btn-label");
          if (!btn || !label) return false;
          return !btn.disabled && !/Checking/i.test(label.textContent || "");
        }""",
        timeout=5000,
    )


def test_update_available_renders_badge_notes_and_whats_new(live_server, browser_page):
    """When update_available=true: the inline "updateBadge" chip has been
    removed (sidebar carries the signal; check button carries the loading
    state), notes render as HTML, version span populates, What's-new
    button shows, Update-now enabled."""
    page = browser_page
    _stub_api_version(
        page,
        {
            "current": "0.64.0",
            "latest": "0.65.0",
            "update_available": True,
            "update_running": False,
            "release_notes": (
                "# v0.65.0 (2026-04-22)\n\n"
                "## 🔺 Fix\n"
                "- Polish release-notes rendering (JTN-900)\n"
                "- Ship backup & restore reshape\n"
            ),
        },
    )
    navigate_and_wait(page, live_server, "/settings")
    _open_maintenance_tab(page)
    _click_check_and_wait(page)

    state = page.evaluate("""() => ({
          badgeExists: !!document.getElementById("updateBadge"),
          checkBtnLabel: (document.querySelector("#checkUpdatesBtn .btn-label").textContent || "").trim(),
          latest: (document.getElementById("latestVersion").textContent || "").trim(),
          notesVersion: (document.getElementById("releaseNotesVersion").textContent || "").trim(),
          notesHidden: document.getElementById("releaseNotesContainer").hidden,
          notesHtml: document.getElementById("releaseNotesBody").innerHTML,
          whatsNewHidden: document.getElementById("whatsNewBtn").hidden,
          updateBtnDisabled: document.getElementById("startUpdateBtn").disabled,
        })""")

    # The old chip is gone entirely — sidebar indicator covers
    # "update available" and the check button itself carries the transient
    # "Checking..." state.
    assert state["badgeExists"] is False
    assert state["checkBtnLabel"] == "Check for updates"
    assert state["latest"] == "0.65.0"
    assert state["notesVersion"] == "\u00b7 v0.65.0"
    assert state["notesHidden"] is False
    assert "<ul>" in state["notesHtml"]
    assert "<li>Polish release-notes rendering (JTN-900)</li>" in state["notesHtml"]
    # The redundant "# v0.65.0" version heading should be stripped.
    assert "v0.65.0" not in state["notesHtml"]
    # "## 🔺 Fix" should be rendered as an h4 category heading.
    assert "<h4>" in state["notesHtml"]
    assert state["whatsNewHidden"] is False
    assert state["updateBtnDisabled"] is False


def test_up_to_date_hides_whats_new_and_disables_update(live_server, browser_page):
    """When already on latest: What's-new hidden, Update-now disabled, but
    release notes disclosure still renders so the user can read the last
    changelog. The inline status chip no longer exists."""
    page = browser_page
    _stub_api_version(
        page,
        {
            "current": "0.64.1",
            "latest": "0.64.1",
            "update_available": False,
            "update_running": False,
            "release_notes": "# v0.64.1\n\n- Stabilize render pipeline\n",
        },
    )
    navigate_and_wait(page, live_server, "/settings")
    _open_maintenance_tab(page)
    _click_check_and_wait(page)

    state = page.evaluate("""() => ({
          badgeExists: !!document.getElementById("updateBadge"),
          whatsNewHidden: document.getElementById("whatsNewBtn").hidden,
          updateBtnDisabled: document.getElementById("startUpdateBtn").disabled,
          notesHtml: document.getElementById("releaseNotesBody").innerHTML,
          notesVersion: (document.getElementById("releaseNotesVersion").textContent || "").trim(),
        })""")

    assert state["badgeExists"] is False
    assert state["whatsNewHidden"] is True
    assert state["updateBtnDisabled"] is True
    assert "<li>Stabilize render pipeline</li>" in state["notesHtml"]
    assert state["notesVersion"] == "\u00b7 v0.64.1"


def test_no_release_notes_hides_disclosure(live_server, browser_page):
    """When release_notes is null the disclosure must stay hidden rather
    than rendering an empty details element."""
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
    navigate_and_wait(page, live_server, "/settings")
    _open_maintenance_tab(page)
    _click_check_and_wait(page)

    state = page.evaluate("""() => ({
          notesHidden: document.getElementById("releaseNotesContainer").hidden,
          notesHtml: document.getElementById("releaseNotesBody").innerHTML,
          whatsNewHidden: document.getElementById("whatsNewBtn").hidden,
        })""")
    assert state["notesHidden"] is True
    assert state["notesHtml"] == ""
    assert state["whatsNewHidden"] is True


def test_render_release_notes_helper_converts_markdown(live_server, browser_page):
    """Unit-check the exposed markdown helper in isolation — no network."""
    page = browser_page
    navigate_and_wait(page, live_server, "/settings")
    html = page.evaluate("""() => window.InkyPiSettingsModules.renderReleaseNotesHTML(
            "# v1.2.3\\n\\n## Fix\\n- A bullet\\n- Another <b>bold</b>\\n\\nPlain line.\\n"
        )""")
    assert "<h4>Fix</h4>" in html
    assert "<ul>" in html and "</ul>" in html
    assert "<li>A bullet</li>" in html
    # HTML entities in list items must be escaped, not rendered as tags.
    assert "<li>Another &lt;b&gt;bold&lt;/b&gt;</li>" in html
    assert "<p>Plain line.</p>" in html
    # The leading version heading should be dropped.
    assert "v1.2.3" not in html
