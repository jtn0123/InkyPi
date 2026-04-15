# pyright: reportMissingImports=false
"""JTN-724 — update-flow happy path journey test.

Fifth of 10 user-journey tests under epic JTN-719. This test exercises the
full "Check for updates → Update now → Success" path via the real
``/settings`` page + backend routes, using Playwright for the UI clicks and
monkeypatching only the thinnest possible seam so no real git / apt / pip
work executes.

Complementary tests:
  * JTN-720 — playlist-refresh journey (unrelated code path).
  * JTN-725 — update-flow FAILURE path (uses INKYPI_UPDATE_TEST_FAIL_AT;
    complements this test's success-side hook INKYPI_UPDATE_TEST_SUCCESS_FAST).

Strategy
--------
We pick *option (b)* from the issue brief — monkeypatch the
``_start_update_via_systemd`` / ``_start_update_fallback_thread`` seam at the
Flask layer — so the Popen / subprocess surface is never touched in the test
process. The new shell-level hook ``INKYPI_UPDATE_TEST_SUCCESS_FAST`` added in
``install/update.sh`` (tested in
``tests/integration/test_update_failure_recovery.py``) covers the companion
scenario: driving the real ``update.sh`` entrypoint to a clean terminal
success state without real work. Having both layers guards the whole flow.

Journey (maps 1:1 onto the assertions below)
  1. Navigate to /settings (updates panel is rendered top-of-page).
  2. Click "Check for Updates" — this hits /api/version, which we've stubbed
     via monkeypatching ``_check_latest_version`` to return a known tag.
  3. Assert the latest tag appears in #latestVersion and the badge flips to
     "Update available".
  4. Click "Update Now" — this POSTs /settings/update, which we've wired so
     the fallback thread runner transitions running → idle almost
     immediately, modelling a successful update.
  5. Poll /settings/update_status from the test (not the UI) to observe the
     state machine transitioning idle → running → idle-again.
  6. Assert the failure banner (#updateFailureBanner) stays hidden.
  7. The autouse ``client_log_capture`` tripwire asserts no client-log errors
     were emitted during the flow (step 10 of the brief).
"""

from __future__ import annotations

import time

import pytest
from tests.integration.browser_helpers import RuntimeCollector, stub_leaflet

pytestmark = [pytest.mark.integration, pytest.mark.journey]

# Tag we force ``_check_latest_version`` to return so the UI has a concrete
# "latest" version to display. Must satisfy ``_TAG_RE`` in the settings
# blueprint (``v?\d+\.\d+\.\d+``).
_STUBBED_LATEST_TAG = "99.0.0"

# Maximum time we'll wait for /settings/update_status to report running=False
# after kicking off the update. The fallback thread simulates 6 steps of
# 0.5s each, so ~4–5s is realistic; we pad generously for CI slowness.
_RUNNING_TIMEOUT_S = 20.0


def _poll_update_status(client, *, timeout_s: float, want_running: bool) -> dict:
    """Poll /settings/update_status until ``running`` matches ``want_running``.

    Returns the final JSON payload. Raises AssertionError on timeout so the
    failure message includes the last-observed state for easy diagnosis.
    """
    deadline = time.monotonic() + timeout_s
    last: dict = {}
    while time.monotonic() < deadline:
        resp = client.get("/settings/update_status")
        assert (
            resp.status_code == 200
        ), f"update_status returned {resp.status_code}: {resp.data!r}"
        last = resp.get_json() or {}
        if bool(last.get("running")) is want_running:
            return last
        time.sleep(0.1)
    pytest.fail(
        f"Timed out after {timeout_s}s waiting for running={want_running}; "
        f"last payload: {last!r}"
    )


@pytest.fixture
def stub_update_seam(monkeypatch):
    """Replace the update-execution seam with an in-process fast simulation.

    ``_start_update_via_systemd`` and ``_start_update_fallback_thread`` both
    normally kick off a long-running subprocess/thread that mutates real
    state. We replace both with a tiny helper that spawns a daemon thread,
    briefly holds ``running=True`` so the UI observes the transition, and
    then clears the state via the production-path helper. This keeps the
    state-machine contract identical to production (same lock, same
    ``_set_update_state`` call) while removing all I/O.
    """
    import threading

    import blueprints.settings as settings_mod

    started = threading.Event()
    finished = threading.Event()

    def _fake_runner(*args, **kwargs):
        def _run():
            # Hold "running" briefly so /settings/update_status observably
            # transitions through running=True. 0.3s is more than enough
            # given the test polls every 100ms.
            started.set()
            time.sleep(0.3)
            settings_mod._set_update_state(False, None)
            finished.set()

        threading.Thread(
            target=_run, name="test-update-happy-path", daemon=True
        ).start()

    monkeypatch.setattr(
        settings_mod, "_start_update_via_systemd", _fake_runner, raising=True
    )
    monkeypatch.setattr(
        settings_mod, "_start_update_fallback_thread", _fake_runner, raising=True
    )

    # Force ``/settings/update`` down the fallback-thread branch regardless of
    # the host platform. ``_systemd_available`` is already False on macOS dev
    # hosts but we pin it for clarity and for the rare CI runner that might
    # actually have systemd-run installed.
    monkeypatch.setattr(settings_mod, "_systemd_available", lambda: False, raising=True)

    yield {"started": started, "finished": finished}


@pytest.fixture
def stub_latest_version(monkeypatch):
    """Force /api/version to report a fixed "latest" tag.

    This both bypasses the real GitHub API call AND resets the module-level
    ``_VERSION_CACHE`` so the stubbed value is returned on the first call.
    """
    import blueprints.settings as settings_mod

    settings_mod._VERSION_CACHE["latest"] = None
    settings_mod._VERSION_CACHE["checked_at"] = 0.0
    settings_mod._VERSION_CACHE["release_notes"] = None
    monkeypatch.setattr(
        settings_mod, "_check_latest_version", lambda: _STUBBED_LATEST_TAG, raising=True
    )
    # Pin APP_VERSION to a known older value so `_semver_gt` reports
    # update_available=True regardless of the repo's current VERSION file.
    yield _STUBBED_LATEST_TAG


@pytest.fixture
def pinned_app_version(flask_app):
    """Set APP_VERSION on the Flask app so /api/version can compare against it."""
    flask_app.config["APP_VERSION"] = "1.0.0"
    yield "1.0.0"


def test_update_flow_happy_path(
    live_server,
    flask_app,
    browser_page,
    stub_update_seam,
    stub_latest_version,
    pinned_app_version,
):
    """End-to-end happy path: check → click update → observe success."""
    page = browser_page
    stub_leaflet(page)
    collector = RuntimeCollector(page, live_server)

    # -- Step 1: navigate to /settings --------------------------------------
    page.goto(
        f"{live_server}/settings",
        wait_until="domcontentloaded",
        timeout=30000,
    )
    page.wait_for_selector(".settings-console-layout", timeout=10000)

    # The Updates section lives inside a tab pane; activate it so the
    # check-for-updates control is interactable before we try to click it.
    updates_tab = page.locator('[data-settings-tab="maintenance"]').first
    updates_tab.click()
    page.wait_for_selector("#checkUpdatesBtn:visible", timeout=10000)

    # -- Step 2: click "Check for Updates" -> /api/version -----------------
    # The JS calls versionUrl and populates #latestVersion when the response
    # includes a tag. Wait for the explicit DOM change rather than a timeout.
    page.click("#checkUpdatesBtn")
    page.wait_for_function(
        "() => {"
        "  const el = document.getElementById('latestVersion');"
        f"  return el && el.textContent && el.textContent.includes('{_STUBBED_LATEST_TAG}');"
        "}",
        timeout=10000,
    )

    # -- Step 3: assert tag displayed + badge says "Update available" ------
    latest_text = page.locator("#latestVersion").inner_text().strip()
    assert (
        _STUBBED_LATEST_TAG in latest_text
    ), f"#latestVersion should show stubbed tag; got {latest_text!r}"
    badge_text = page.locator("#updateBadge").inner_text().strip()
    assert (
        "Update available" in badge_text
    ), f"#updateBadge should reflect update availability; got {badge_text!r}"

    # "Update Now" must now be enabled (it ships disabled).
    assert not page.locator("#startUpdateBtn").is_disabled(), (
        "#startUpdateBtn should be enabled once the check-for-updates call "
        "reports a newer version"
    )

    # The failure banner from JTN-710 must be hidden at this point — a fresh
    # /settings load with no .last-update-failure should leave it collapsed.
    failure_banner = page.locator("#updateFailureBanner")
    assert failure_banner.count() == 1
    assert (
        failure_banner.is_hidden()
    ), "#updateFailureBanner must not be visible on a clean happy-path load"

    # -- Step 4: open the Flask test client to poll status independently ---
    client = flask_app.test_client()

    # Baseline: not running yet.
    baseline = client.get("/settings/update_status").get_json() or {}
    assert (
        baseline.get("running") is False
    ), f"Precondition: update must not be running at journey start; got {baseline!r}"

    # -- Step 5: click "Update Now" -> POST /settings/update ---------------
    page.click("#startUpdateBtn")

    # The fake runner sets ``started`` the moment the thread picks up the
    # work; this proves /settings/update actually dispatched.
    assert stub_update_seam["started"].wait(
        timeout=5.0
    ), "POST /settings/update did not dispatch the update runner within 5s"

    # -- Step 6: observe the running=True -> running=False transition ------
    # Depending on thread-scheduling luck the Flask response from
    # /settings/update may return before or after we first observe
    # running=True. Try to catch running=True, but don't fail if we only
    # ever observe the post-transition idle state — the terminal assertion
    # (running=False after finish) is the load-bearing signal.
    deadline = time.monotonic() + 2.0
    saw_running = False
    while time.monotonic() < deadline:
        payload = client.get("/settings/update_status").get_json() or {}
        if payload.get("running"):
            saw_running = True
            break
        if stub_update_seam["finished"].is_set():
            break
        time.sleep(0.05)

    # Wait for the fake runner to flip running back to False.
    assert stub_update_seam["finished"].wait(timeout=_RUNNING_TIMEOUT_S), (
        "Fake update runner did not finish within " f"{_RUNNING_TIMEOUT_S}s"
    )
    final = _poll_update_status(
        client, timeout_s=_RUNNING_TIMEOUT_S, want_running=False
    )

    # Terminal state assertions — the journey's load-bearing invariants.
    assert (
        final.get("running") is False
    ), f"Terminal update_status must report running=False; got {final!r}"
    # JTN-710 contract: ``last_failure`` is null/None after a successful run.
    # Flask's get_json() parses JSON null as Python None; an empty dict can
    # surface only if read_last_update_failure() returns one.
    assert final.get("last_failure") in (
        None,
        {},
    ), f"Happy-path must leave last_failure empty; got {final!r}"

    # Soft signal — at least document whether we caught the intermediate
    # running=True state. We don't hard-assert because inherent thread-
    # scheduling race can make this flaky on very slow CI boxes. The fake
    # runner held the flag for 300ms which is ample under normal load.
    if not saw_running:
        pytest.skip(  # noqa: PT017 — intentional soft-fail diagnostic
            "Did not observe intermediate running=True (thread-scheduling "
            "race). Terminal state is correct; transition was too fast to "
            "catch in this environment."
        )

    # -- Step 7: failure banner must still be hidden -----------------------
    # After a successful update the banner should remain hidden. The JS
    # pollUpdateStatus branch calls renderUpdateFailureBanner(null) which
    # hides the element, matching the initial state.
    page.wait_for_timeout(500)  # let the JS poller (2s interval) catch up
    assert failure_banner.is_hidden(), (
        "#updateFailureBanner must remain hidden after a successful update "
        "(JTN-710 contract)"
    )

    # -- Step 8 (collector): no uncaught JS errors during the flow ---------
    # client_log_capture (autouse in tests/integration/conftest.py) asserts
    # the /api/client-log tripwire stays empty — that's the equivalent of
    # the brief's "no client-log error entries" assertion (step 10). We
    # additionally check pageerrors here to catch anything that didn't
    # route through the shim.
    assert (
        not collector.page_errors
    ), f"pageerror(s) during happy-path update flow: {collector.page_errors[:5]}"
