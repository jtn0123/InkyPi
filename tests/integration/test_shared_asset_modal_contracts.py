"""Real-browser parity and keyboard contracts for both shared asset modes."""

import importlib.util
import json
import os
from collections.abc import Callable
from pathlib import Path

import pytest
from flask import Flask
from PIL import Image
from playwright.sync_api import Page, Route, expect
from tests.integration.browser_helpers import navigate_and_wait

pytestmark = [
    pytest.mark.skipif(
        os.getenv("SKIP_UI", "").lower() in {"1", "true"},
        reason="UI interactions skipped by env",
    ),
    pytest.mark.flaky(reruns=0),
]
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(params=[False, True], ids=["fallback", "bundled"])
def asset_mode(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    flask_app: Flask,
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> bool:
    image_dir = Path(flask_app.config["DEVICE_CONFIG"].history_image_dir)
    Image.new("RGB", (4, 4), "white").save(image_dir / "display_20260930_120000.png")
    bundled = bool(request.param)
    monkeypatch.setitem(flask_app.jinja_env.globals, "bundled_assets_enabled", bundled)
    if bundled:
        spec = importlib.util.spec_from_file_location(
            "build_assets", ROOT / "scripts/build_assets.py"
        )
        assert spec is not None and spec.loader is not None
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        monkeypatch.setattr(builder, "DIST_DIR", tmp_path)
        builder.main([])
        manifest = json.loads((tmp_path / "manifest.json").read_text())
        monkeypatch.setitem(flask_app.jinja_env.globals, "bundled_asset", manifest.get)

        def serve_asset(path: Path) -> Callable[[Route], None]:
            def fulfill(route: Route) -> None:
                route.fulfill(path=path)

            return fulfill

        for filename in manifest.values():
            browser_page.route(
                f"**/static/dist/{filename}*", serve_asset(tmp_path / filename)
            )
    return bundled


def test_diagnostics_and_theme_exist_in_both_modes(
    asset_mode: bool, live_server: str, browser_page: Page
) -> None:
    page = browser_page
    navigate_and_wait(page, live_server, "/")
    page.wait_for_function(
        "() => window.InkyPiTheme && window.__statusBadge && window.__debugConsole && window.InkyPiModalFocus"
    )
    assert page.locator("html").get_attribute("data-theme") in {"light", "dark"}
    # Force the reporter's sample decision only for this deliberate test event.
    with page.expect_request("**/api/client-error") as report:
        page.evaluate("""() => {
            const previous = Math.random;
            Math.random = () => 0;
            window.dispatchEvent(new ErrorEvent('error', {message:'asset parity probe'}));
            Math.random = previous;
        }""")
    assert "asset parity probe" in (report.value.post_data or "")


@pytest.mark.parametrize(
    ("path", "trigger", "modal"),
    [
        ("/settings", "rebootBtn", "rebootConfirmModal"),
        ("/history", "historyClearBtn", "clearHistoryModal"),
    ],
)
def test_dialog_wraps_focus_and_restores_trigger(
    asset_mode: bool,
    live_server: str,
    browser_page: Page,
    path: str,
    trigger: str,
    modal: str,
) -> None:
    page = browser_page
    navigate_and_wait(page, live_server, path)
    if path == "/settings":
        page.locator('[data-settings-tab="power"]').click()
    button = page.locator(f"#{trigger}")
    button.click()
    dialog = page.locator(f"#{modal}")
    expect(dialog).to_be_visible()
    controls = dialog.locator("button:visible:not([disabled])")
    expect(controls.first).to_be_focused()
    controls.last.focus()
    page.keyboard.press("Tab")
    expect(controls.first).to_be_focused()
    page.keyboard.press("Shift+Tab")
    expect(controls.last).to_be_focused()
    assert page.locator(".shell-sidebar").evaluate("node => !!node.closest('[inert]')")
    page.keyboard.press("Escape")
    expect(dialog).to_be_hidden()
    expect(button).to_be_focused()
    assert not page.locator(".shell-sidebar").evaluate(
        "node => !!node.closest('[inert]')"
    )


def test_nested_dialog_restores_outer_focus(
    asset_mode: bool, live_server: str, browser_page: Page
) -> None:
    page = browser_page
    navigate_and_wait(page, live_server, "/settings")
    page.locator('[data-settings-tab="power"]').click()
    page.locator("#rebootBtn").click()
    expect(page.locator("#rebootConfirmModal")).to_be_visible()
    page.evaluate("""() => {
        const trigger = document.getElementById('cancelRebootBtn');
        trigger.focus();
        const dialog = document.createElement('div');
        dialog.id = 'nestedFocusProbe';
        dialog.setAttribute('role', 'dialog');
        dialog.innerHTML = '<button id="nestedFocusClose">Close</button>';
        document.body.append(dialog);
        const close = () => {dialog.hidden = true; InkyPiModalFocus.deactivate(dialog);};
        InkyPiModalFocus.activate(dialog, trigger, close);
    }""")
    expect(page.locator("#nestedFocusClose")).to_be_focused()
    page.keyboard.press("Escape")
    expect(page.locator("#nestedFocusProbe")).to_be_hidden()
    expect(page.locator("#cancelRebootBtn")).to_be_focused()
    expect(page.locator("#rebootConfirmModal")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.locator("#rebootBtn")).to_be_focused()
