# pyright: reportMissingImports=false
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_UI", "").lower() in ("1", "true"),
    reason="UI interactions skipped by env",
)

from tests.integration.browser_helpers import navigate_and_wait  # noqa: E402


def test_plugin_settings_form_has_fields(
    live_server: str, browser_page: Page, tmp_path: Path
) -> None:
    page = browser_page
    rc = navigate_and_wait(page, live_server, "/plugin/clock")

    form = page.locator("#settingsForm")
    form.wait_for(state="visible", timeout=5000)
    assert form.is_visible(), "Settings form should be visible on plugin page"

    inputs = form.locator("input, select, textarea")
    assert inputs.count() > 0, "Settings form should contain input fields"

    rc.assert_no_errors(str(tmp_path), "plugin_form_fields")


def test_plugin_settings_form_fields_editable(
    live_server: str, browser_page: Page, tmp_path: Path
) -> None:
    page = browser_page
    # Use todo_list which has a text field ("title"); the clock plugin has
    # only color pickers and a custom clock-face radio widget, no text inputs.
    rc = navigate_and_wait(page, live_server, "/plugin/todo_list")

    form = page.locator("#settingsForm")
    form.wait_for(state="visible", timeout=5000)

    text_input = form.locator("input[type='text'], input:not([type])")
    assert text_input.count() > 0, "Form should have at least one text input"
    first_input = text_input.first
    first_input.fill("test-value-123")
    value = first_input.input_value()
    assert value == "test-value-123", f"Input should accept typed value, got '{value}'"

    rc.assert_no_errors(str(tmp_path), "plugin_form_editable")


def test_plugin_page_renders_both_workflow_panels(
    live_server: str, mobile_page: Page, tmp_path: Path
) -> None:
    # Design refresh (post-JTN-89) -> None -> None: the Configure/Preview mode toggle was
    # retired in favor of always showing both panels stacked on mobile and
    # side-by-side on desktop. Confirm both panels render and neither is
    # hidden behind an aria-hidden / inert gate.
    page = mobile_page
    rc = navigate_and_wait(page, live_server, "/plugin/clock")

    configure_panel = page.locator("[data-workflow-panel='configure']")
    preview_panel = page.locator("[data-workflow-panel='preview']")

    assert configure_panel.count() > 0, "Configure workflow panel should exist"
    assert preview_panel.count() > 0, "Preview workflow panel should exist"

    # Mode bar should be gone entirely.
    assert page.locator(".workflow-mode-bar").count() == 0
    assert page.locator("[data-workflow-mode]").count() == 0

    # Both panels should be visible / not inert.
    for panel in (configure_panel.first, preview_panel.first):
        assert panel.is_visible(), "workflow panel should be visible"
        assert panel.get_attribute("inert") is None

    rc.assert_no_errors(str(tmp_path), "plugin_workflow_panels_always_visible")


def test_last_progress_card_persistent_in_aside(
    live_server: str, browser_page: Page, tmp_path: Path
) -> None:
    """Design refresh: the Progress card is now a persistent aside card, not a
    fixed overlay. Confirm it renders on load with an empty state (no snapshot
    in localStorage) and that clicking ``#showLastProgressBtn`` reloads the
    content without toggling visibility.
    """
    page = browser_page

    # Clear cached progress before the page boots so the empty-state branch
    # runs during init — and so the click handler also sees no data.
    rc = navigate_and_wait(page, live_server, "/plugin/clock")
    page.evaluate("() => { try { localStorage.clear(); } catch (_) {} }")

    progress = page.locator("#requestProgress")
    assert progress.count() == 1, "#requestProgress card should render"
    # Always visible in the aside — no `hidden` attribute gating.
    assert (
        progress.evaluate("(el) => el.hidden") is False
    ), "#requestProgress should be visible by default (persistent aside card)"
    # The card should sit inside the aside workflow panel, not as a fixed overlay.
    assert progress.evaluate(
        "(el) => !!el.closest('[data-workflow-panel=\"preview\"]')"
    ), "#requestProgress should be a child of the preview side panel"

    # Clicking the header button re-renders the empty-state content; the card
    # remains visible either way.
    page.locator("#showLastProgressBtn").click()
    page.wait_for_timeout(150)

    assert progress.evaluate(
        "(el) => !el.hidden"
    ), "#requestProgress should remain visible after clicking Last Progress"
    empty = page.locator(".progress-empty-state")
    assert empty.count() == 1, "no-data empty state should render when unseeded"

    # Close button is gone — the card is always visible in the aside.
    assert (
        page.locator("#closeProgressBtn").count() == 0
    ), "#closeProgressBtn should be removed (card is always visible now)"

    rc.assert_no_errors(str(tmp_path), "plugin_last_progress_persistent_card")


@pytest.fixture
def upload_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Store Image Upload files in a temp folder, not src/static/images/saved."""
    import plugins.image_upload.image_upload as image_upload_mod
    import utils.app_utils as app_utils

    saved = tmp_path / "saved"
    saved.mkdir()
    real_resolve_path = app_utils.resolve_path
    target = os.path.join("static", "images", "saved")
    monkeypatch.setattr(
        app_utils,
        "resolve_path",
        lambda p: str(saved) if os.fspath(p) == target else real_resolve_path(p),
    )
    monkeypatch.setattr(image_upload_mod, "_get_upload_dir", lambda: str(saved))
    return saved


def _pick_image(page: Page, tmp_path: Path, name: str = "garden.png") -> None:
    from PIL import Image

    picked = tmp_path / name
    Image.new("RGB", (40, 30), "white").save(picked)
    page.set_input_files("#imageUpload", str(picked))
    page.wait_for_selector(f"[id='added-{name}']", timeout=5000)


def test_image_upload_update_display_sends_picked_files(
    live_server: str, browser_page: Page, tmp_path: Path, upload_dir: Path
) -> None:
    page = browser_page
    rc = navigate_and_wait(page, live_server, "/plugin/image_upload")
    _pick_image(page, tmp_path)

    sent: list[bytes] = []

    def fake_update_now(route: Any) -> None:
        sent.append(route.request.post_data_buffer or b"")
        route.fulfill(
            status=200,
            content_type="application/json",
            body='{"success": true, "message": "Display updated"}',
        )

    page.route("**/update_now", fake_update_now)
    page.locator("[data-plugin-action='update_now']").first.click()
    page.wait_for_selector(".toast-content", timeout=10000)

    assert sent, "Update display never sent a request"
    assert b'name="imageFiles[]"; filename="garden.png"' in sent[0]
    rc.assert_no_errors(str(tmp_path), "image_upload_update_now")


def test_image_upload_save_stores_picked_files(
    live_server: str, browser_page: Page, tmp_path: Path, upload_dir: Path
) -> None:
    page = browser_page
    rc = navigate_and_wait(page, live_server, "/plugin/image_upload")
    _pick_image(page, tmp_path)
    # A second pick that is removed again before saving must not be sent.
    _pick_image(page, tmp_path, "beach.png")
    page.locator("[id='added-beach.png'] .remove-btn").click()
    assert page.locator("[id='added-beach.png']").count() == 0

    with page.expect_request(lambda r: "/save_plugin_settings" in r.url) as req_info:
        page.locator("#savePluginSettingsBtn").click()
    request = req_info.value
    body = request.post_data_buffer or b""
    assert "multipart/form-data" in (request.headers.get("content-type") or "")
    assert b'name="imageFiles[]"; filename="garden.png"' in body
    assert b'filename="beach.png"' not in body

    # Once saved, the widget lists the stored copy as a saved image and drops
    # the pending file, so the next save keeps it instead of re-uploading it.
    hidden = page.locator("#hiddenFileInputs input[name='imageFiles[]']")
    hidden.first.wait_for(state="attached", timeout=10000)
    stored = Path(hidden.first.get_attribute("value") or "")
    assert stored.parent == upload_dir
    assert stored.name.endswith("_garden.png")
    assert stored.is_file()
    assert page.locator("[id='added-garden.png']").count() == 0
    assert page.evaluate("() => window.uploadedFiles['imageFiles[]'].length") == 0
    rc.assert_no_errors(str(tmp_path), "image_upload_save")
