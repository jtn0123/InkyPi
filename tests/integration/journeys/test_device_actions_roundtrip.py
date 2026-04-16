# pyright: reportMissingImports=false
"""Device-actions journey for the Settings page (epic JTN-719).

This fills the "Device actions — reboot/shutdown confirm modal, cancel,
confirm path" gap from the journey epic. Static/unit tests already verify the
markup and route contract; this browser journey verifies the full user flow:

1. Open the reboot confirm modal and verify no backend action fires yet.
2. Cancel and confirm focus/state return cleanly.
3. Re-open and confirm reboot; assert the real ``/shutdown`` POST executes
   with ``{"reboot": true}``.
4. Repeat the same flow for shutdown and assert the command switches to
   ``sudo shutdown -h now`` only on confirm.
"""

from __future__ import annotations

import os

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.journey,
    pytest.mark.skipif(
        os.getenv("SKIP_BROWSER", "").lower() in ("1", "true")
        or os.getenv("SKIP_UI", "").lower() in ("1", "true"),
        reason="Browser/UI tests skipped by env",
    ),
]

from tests.integration.browser_helpers import (  # noqa: E402
    RuntimeCollector,
    stub_leaflet,
)


@pytest.fixture
def device_action_calls(monkeypatch):
    """Capture reboot/shutdown subprocess calls without touching the host."""
    import subprocess

    calls: list[list[str]] = []

    def _fake_run(cmd, check=True):
        calls.append(list(cmd))

    monkeypatch.setattr(subprocess, "run", _fake_run)
    return calls


@pytest.fixture
def reset_shutdown_limiter():
    """Keep the shared shutdown limiter from leaking into later tests."""
    import blueprints.settings as settings_mod

    settings_mod._shutdown_limiter.reset()
    yield settings_mod
    settings_mod._shutdown_limiter.reset()


def _open_settings_device_panel(page, live_server: str) -> RuntimeCollector:
    stub_leaflet(page)
    collector = RuntimeCollector(page, live_server)
    page.goto(
        f"{live_server}/settings",
        wait_until="domcontentloaded",
        timeout=30000,
    )
    page.wait_for_selector("[data-page-shell]", timeout=10000)
    page.evaluate("""() => {
            window.__journeyMessages = [];
            const original = window.showResponseModal;
            window.showResponseModal = function(status, message, ...rest) {
              window.__journeyMessages.push({ status, message: String(message) });
              return original.call(this, status, message, ...rest);
            };
        }""")
    page.locator('[data-settings-tab="maintenance"]').first.click()
    page.wait_for_selector("#rebootBtn", timeout=10000)
    page.wait_for_selector("#shutdownBtn", timeout=10000)
    return collector


def _assert_response_message(page, text: str) -> None:
    page.wait_for_function(
        """(expected) => {
            const messages = window.__journeyMessages || [];
            return messages.some((entry) =>
              entry &&
              typeof entry.message === 'string' &&
              entry.message.includes(expected)
            );
        }""",
        arg=text,
        timeout=5000,
    )


def test_device_actions_confirm_cancel_paths(
    live_server,
    browser_page,
    device_action_calls,
    reset_shutdown_limiter,
):
    """Reboot/shutdown only execute on confirm, never on initial click/cancel."""
    page = browser_page
    collector = _open_settings_device_panel(page, live_server)

    reboot_btn = page.locator("#rebootBtn")
    reboot_modal = page.locator("#rebootConfirmModal")
    shutdown_btn = page.locator("#shutdownBtn")
    shutdown_modal = page.locator("#shutdownConfirmModal")

    # Reboot: open -> cancel. This must not call the backend.
    reboot_btn.click()
    reboot_modal.wait_for(state="visible", timeout=5000)
    assert device_action_calls == []
    page.locator("#cancelRebootBtn").click()
    reboot_modal.wait_for(state="hidden", timeout=5000)
    page.wait_for_function(
        "() => document.activeElement && document.activeElement.id === 'rebootBtn'",
        timeout=3000,
    )
    assert device_action_calls == []

    # Reboot: open -> confirm. This should call /shutdown with reboot=true
    # and surface the reboot copy in the response modal.
    reboot_btn.click()
    reboot_modal.wait_for(state="visible", timeout=5000)
    with page.expect_response(
        lambda response: response.url.endswith("/shutdown")
        and response.request.method == "POST"
        and response.status == 200,
        timeout=7000,
    ) as reboot_info:
        page.locator("#confirmRebootBtn").click()
    assert reboot_info.value.status == 200
    reboot_modal.wait_for(state="hidden", timeout=5000)
    _assert_response_message(page, "The system is rebooting.")
    assert device_action_calls == [["sudo", "reboot"]]

    # Clear the cooldown so the shutdown half of the journey can run in the
    # same test without tripping the 30s safety limiter.
    reset_shutdown_limiter._shutdown_limiter.reset()

    # Shutdown: open -> cancel. Still no additional backend action.
    shutdown_btn.click()
    shutdown_modal.wait_for(state="visible", timeout=5000)
    assert device_action_calls == [["sudo", "reboot"]]
    page.locator("#cancelShutdownBtn").click()
    shutdown_modal.wait_for(state="hidden", timeout=5000)
    page.wait_for_function(
        "() => document.activeElement && document.activeElement.id === 'shutdownBtn'",
        timeout=3000,
    )
    assert device_action_calls == [["sudo", "reboot"]]

    # Shutdown: open -> confirm. This should POST reboot=false and call the
    # shutdown command only once the user confirms.
    shutdown_btn.click()
    shutdown_modal.wait_for(state="visible", timeout=5000)
    with page.expect_response(
        lambda response: response.url.endswith("/shutdown")
        and response.request.method == "POST"
        and response.status == 200,
        timeout=7000,
    ) as shutdown_info:
        page.locator("#confirmShutdownBtn").click()
    assert shutdown_info.value.status == 200
    shutdown_modal.wait_for(state="hidden", timeout=5000)
    _assert_response_message(page, "The system is shutting down.")
    assert device_action_calls == [
        ["sudo", "reboot"],
        ["sudo", "shutdown", "-h", "now"],
    ]

    collector.assert_no_errors(name="journey_device_actions")
