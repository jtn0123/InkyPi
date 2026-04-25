# pyright: reportMissingImports=false
"""Journey tests for Device/Update/Ops flows (JTN-728/JTN-727/JTN-726/JTN-725).

Focus areas from the issue bundle:
1. Reboot + shutdown confirmations dispatch the correct backend commands.
2. Logs panel refresh/filter controls remain functional.
3. Refresh cadence changes persist through the settings save flow.
4. Update failure metadata is surfaced and rollback recovery can be started.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest
from tests.integration.browser_helpers import RuntimeCollector, stub_leaflet

pytestmark = [pytest.mark.integration, pytest.mark.journey]

_STUBBED_LATEST_TAG = "99.0.0"


@pytest.fixture
def stable_version_check(monkeypatch):
    """Force /api/version to stay local/deterministic during settings journeys."""
    import blueprints.settings as settings_mod

    settings_mod._VERSION_CACHE["latest"] = None
    settings_mod._VERSION_CACHE["checked_at"] = 0.0
    settings_mod._VERSION_CACHE["release_notes"] = None
    settings_mod._VERSION_CACHE["last_error"] = None
    # Accept the ``force_refresh`` kwarg the real implementation added so the
    # "Check for updates" button's ?force=1 path works without 500ing.
    monkeypatch.setattr(
        settings_mod,
        "_check_latest_version",
        lambda force_refresh=False: _STUBBED_LATEST_TAG,
        raising=True,
    )


def _open_settings_page(page, live_server: str) -> RuntimeCollector:
    stub_leaflet(page)
    collector = RuntimeCollector(page, live_server)
    page.goto(f"{live_server}/settings", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_selector(".settings-console-layout", timeout=10000)
    page.wait_for_selector("#logsViewer", state="attached", timeout=10000)
    return collector


def _open_updates_tab(page) -> None:
    page.locator('[data-settings-tab="maintenance"]').first.click()
    page.wait_for_selector("#checkUpdatesBtn:visible", timeout=10000)


def _open_power_tab(page) -> None:
    # Reboot/shutdown moved to a dedicated "Power" tab (handoff design parity).
    page.locator('[data-settings-tab="power"]').first.click()
    page.wait_for_selector("#rebootBtn:visible", timeout=10000)


def _viewer_lines(page) -> list[str]:
    raw = page.locator("#logsViewer").inner_text()
    return [line for line in raw.splitlines() if line.strip()]


def _ensure_logs_panel_open(page) -> None:
    viewer = page.locator("#logsViewer")
    if viewer.is_visible():
        return
    toggle = page.locator("#settingsLogsToggle")
    if toggle.count():
        toggle.click()
    page.wait_for_selector("#logsViewer:visible", timeout=5000)


def _wait_for_toast_message(page, text: str, timeout: int = 10000) -> None:
    page.wait_for_function(
        "(needle) => Array.from(document.querySelectorAll('.toast .toast-content'))"
        ".some((el) => (el.textContent || '').includes(needle))",
        arg=text,
        timeout=timeout,
    )


def test_jtn_728_reboot_shutdown_journey(
    live_server,
    browser_page,
    monkeypatch,
    stable_version_check,
):
    """JTN-728: Reboot/shutdown controls open confirms and hit /shutdown."""
    import blueprints.settings as settings_mod
    from blueprints.settings import _system as system_mod

    # Keep the test focused on command dispatch, not cooldown timing.
    monkeypatch.setattr(
        settings_mod._shutdown_limiter, "check", lambda: (True, 0.0), raising=True
    )
    monkeypatch.setattr(
        settings_mod._shutdown_limiter, "record", lambda: None, raising=True
    )
    monkeypatch.setattr(
        settings_mod._shutdown_limiter, "reset", lambda: None, raising=True
    )

    calls: list[list[str]] = []

    def _fake_run(cmd, check=True):  # noqa: FBT002 - signature mirrors subprocess.run
        calls.append(list(cmd))

        class _Result:
            returncode = 0

        return _Result()

    monkeypatch.setattr(system_mod.subprocess, "run", _fake_run, raising=True)

    page = browser_page
    collector = _open_settings_page(page, live_server)
    _open_power_tab(page)

    # Reboot path
    page.click("#rebootBtn")
    page.wait_for_selector("#rebootConfirmModal:not([hidden])", timeout=5000)
    page.click("#confirmRebootBtn")
    deadline = time.monotonic() + 5.0
    while len(calls) < 1 and time.monotonic() < deadline:
        page.wait_for_timeout(100)
    assert (
        len(calls) >= 1
    ), "Expected reboot confirm to POST /shutdown and run reboot cmd"
    assert calls[0] == ["sudo", "reboot"], f"Unexpected reboot command: {calls[0]!r}"

    # Shutdown path
    page.click("#shutdownBtn")
    page.wait_for_selector("#shutdownConfirmModal:not([hidden])", timeout=5000)
    page.click("#confirmShutdownBtn")
    deadline = time.monotonic() + 5.0
    while len(calls) < 2 and time.monotonic() < deadline:
        page.wait_for_timeout(100)
    assert (
        len(calls) >= 2
    ), "Expected shutdown confirm to POST /shutdown and run shutdown cmd"
    assert calls[1] == ["sudo", "shutdown", "-h", "now"], (
        "Unexpected shutdown command: " f"{calls[1]!r}"
    )

    collector.assert_no_errors(name="jtn_728_reboot_shutdown")


def test_jtn_727_logs_journey(
    live_server,
    browser_page,
    monkeypatch,
    stable_version_check,
):
    """JTN-727: Logs refresh/filter controls keep rendering expected output."""
    import blueprints.settings as settings_mod

    counter = {"n": 0}

    def _fake_read_log_lines(hours: int) -> list[str]:
        counter["n"] += 1
        n = counter["n"]
        return [
            f"Apr 16 00:00:00 [INFO] service-{n}: boot complete",
            f"Apr 16 00:00:01 [WARNING] service-{n}: disk usage high",
            f"Apr 16 00:00:02 [ERROR] service-{n}: update failed",
            f"Apr 16 00:00:03 [INFO] service-{n}: heartbeat",
        ]

    monkeypatch.setattr(
        settings_mod, "_rate_limit_ok", lambda _addr: True, raising=True
    )
    monkeypatch.setattr(
        settings_mod, "_read_log_lines", _fake_read_log_lines, raising=True
    )

    page = browser_page
    collector = _open_settings_page(page, live_server)
    _ensure_logs_panel_open(page)

    page.wait_for_function(
        "() => /service-\\d+/.test(document.getElementById('logsViewer')?.textContent || '')",
        timeout=10000,
    )
    assert any("service-" in line for line in _viewer_lines(page))

    before_refresh = page.locator("#logsViewer").inner_text()
    before_calls = counter["n"]
    page.click("#logsRefreshBtn")
    page.wait_for_function(
        "(prior) => document.getElementById('logsViewer')?.textContent !== prior",
        arg=before_refresh,
        timeout=10000,
    )
    assert counter["n"] >= before_calls + 1
    assert any("service-" in line for line in _viewer_lines(page))

    # Client-side filter
    page.fill("#logsFilter", "disk usage")
    page.wait_for_timeout(350)  # debounced input path
    filtered = _viewer_lines(page)
    assert (
        len(filtered) == 1
    ), f"Filter should narrow logs to one line, got {filtered!r}"
    assert "WARNING" in filtered[0]

    # Level filter (warnings + errors) with filter cleared.
    page.fill("#logsFilter", "")
    page.select_option("#logsLevel", "warn_errors")
    page.wait_for_timeout(200)
    leveled = _viewer_lines(page)
    assert (
        len(leveled) == 2
    ), f"warn_errors should keep exactly 2 lines, got {leveled!r}"
    assert all(("WARNING" in line or "ERROR" in line) for line in leveled)

    updated = page.locator("#logsUpdated").inner_text().strip()
    assert updated.startswith(
        "Updated "
    ), f"logsUpdated should show timestamp, got {updated!r}"

    collector.assert_no_errors(name="jtn_727_logs")


def test_jtn_726_refresh_cadence_journey(
    live_server,
    flask_app,
    device_config_dev,
    browser_page,
    monkeypatch,
    stable_version_check,
):
    """JTN-726: Changing cadence in Settings persists + signals refresh task."""
    signal_calls = {"count": 0}

    def _signal_config_change():
        signal_calls["count"] += 1

    monkeypatch.setattr(
        flask_app.config["REFRESH_TASK"],
        "signal_config_change",
        _signal_config_change,
        raising=True,
    )

    page = browser_page
    collector = _open_settings_page(page, live_server)

    page.click('[data-settings-tab="scheduling"]')
    page.wait_for_selector('[data-settings-panel="scheduling"].active', timeout=5000)

    # The scheduling panel's display-cycle section is now flat (no collapsible
    # toggle), so the interval input is visible once the panel is active.
    page.wait_for_selector("#interval:visible", timeout=5000)

    assert page.locator("#interval").input_value() == "5"
    assert page.locator("#unit").input_value() == "minute"
    assert page.locator("#saveSettingsBtn").is_disabled()

    page.fill("#interval", "2")
    page.select_option("#unit", "hour")
    page.wait_for_function(
        "() => !document.getElementById('saveSettingsBtn').disabled", timeout=5000
    )

    page.click("#saveSettingsBtn")
    _wait_for_toast_message(page, "Saved settings.", timeout=10000)

    assert device_config_dev.get_config("plugin_cycle_interval_seconds") == 7200
    assert signal_calls["count"] == 1, "Cadence change should signal refresh task once"

    collector.assert_no_errors(name="jtn_726_refresh_cadence")


def test_jtn_725_update_failure_recovery_journey(
    live_server,
    flask_app,
    browser_page,
    monkeypatch,
    tmp_path: Path,
    stable_version_check,
):
    """JTN-725: Failed-update banner renders and rollback recovery can be started."""
    import blueprints.settings as settings_mod

    state_dir = tmp_path / "update_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / ".last-update-failure").write_text(
        json.dumps(
            {
                "timestamp": "2026-04-16T01:02:03Z",
                "exit_code": 97,
                "last_command": "apt_install",
                "recent_journal_lines": "E: package failure\nTraceback: mock",
            }
        ),
        encoding="utf-8",
    )
    (state_dir / "prev_version").write_text("v1.2.2", encoding="utf-8")
    monkeypatch.setenv("INKYPI_LOCKFILE_DIR", str(state_dir))

    started = threading.Event()
    rollback_targets: list[str | None] = []

    def _fake_runner(script_path, target_tag=None):
        rollback_targets.append(target_tag)
        started.set()
        settings_mod._set_update_state(False, None)

    monkeypatch.setattr(settings_mod, "_systemd_available", lambda: False, raising=True)
    monkeypatch.setattr(
        settings_mod, "_start_update_fallback_thread", _fake_runner, raising=True
    )

    page = browser_page
    collector = _open_settings_page(page, live_server)
    _open_updates_tab(page)

    page.wait_for_function(
        "() => !document.getElementById('updateFailureBanner')?.hidden", timeout=10000
    )
    assert "exit 97" in page.locator("#updateFailureExitCode").inner_text()
    assert "apt_install" in page.locator("#updateFailureStep").inner_text()
    assert page.locator("#rollbackUpdateBtn").is_visible()
    assert "v1.2.2" in page.locator("#rollbackTargetVersion").inner_text()

    page.click("#rollbackUpdateBtn")
    page.wait_for_selector("#rollbackConfirmModal:not([hidden])", timeout=5000)
    assert "v1.2.2" in page.locator("#rollbackConfirmVersion").inner_text()
    page.click("#confirmRollbackBtn")

    assert started.wait(timeout=5.0), "Rollback did not dispatch fallback runner"
    assert rollback_targets == ["v1.2.2"]

    _wait_for_toast_message(page, "Rollback to v1.2.2 started.", timeout=10000)

    status = flask_app.test_client().get("/settings/update_status").get_json() or {}
    assert status.get("running") is False
    assert status.get("prev_version") == "v1.2.2"
    assert (status.get("last_failure") or {}).get("exit_code") == 97

    collector.assert_no_errors(name="jtn_725_update_failure_recovery")
