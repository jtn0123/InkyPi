# pyright: reportMissingImports=false
"""Playlist round-trip journey test (JTN-721, epic JTN-719).

Journey: create playlist -> add 3 plugins -> reorder (move 3rd to top) ->
delete middle -> reload -> assert only the 2 expected items remain in the
post-reorder, post-delete order. Persistence through reload is the critical
correctness check (catches silent "save was a no-op" regressions).
"""

from __future__ import annotations

import json
import os
import uuid

import pytest

pytestmark = [
    pytest.mark.journey,
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("SKIP_BROWSER", "").lower() in ("1", "true")
        or os.getenv("SKIP_UI", "").lower() in ("1", "true"),
        reason="Browser/UI tests skipped by env",
    ),
]

from tests.integration.browser_helpers import navigate_and_wait  # noqa: E402

# Three plugin_ids known to be reliably registered in the repo.
# clock has no required config so instances can be seeded without extra setup.
_PLUGINS = [
    ("clock", "Step1 Clock"),
    ("clock", "Step2 Clock"),
    ("clock", "Step3 Clock"),
]


def _seed_plugins(device_config, playlist_name, instances):
    """Add plugin instances to a playlist via the manager (skips UI/CSRF)."""
    pm = device_config.get_playlist_manager()
    playlist = pm.get_playlist(playlist_name)
    assert playlist is not None, f"Playlist {playlist_name!r} not found for seeding"
    for plugin_id, name in instances:
        assert playlist.add_plugin(
            {
                "plugin_id": plugin_id,
                "name": name,
                "plugin_settings": {},
                "refresh": {"interval": 300},
            }
        ), f"Failed to seed {plugin_id}/{name}"
    device_config.write_config()


def _dom_instance_names(page, playlist_name):
    """Return the list of instance names for a playlist, in DOM order."""
    return page.evaluate(
        """(pn) => {
            const card = Array.from(document.querySelectorAll('.playlist-item'))
              .find(el => el.getAttribute('data-playlist-name') === pn);
            if (!card) return null;
            return Array.from(card.querySelectorAll('.plugin-item'))
              .map(el => el.getAttribute('data-instance-name'));
        }""",
        playlist_name,
    )


def _backend_instance_names(device_config, playlist_name):
    """Re-read the on-disk config and return instance names for the playlist.

    Re-loading via ``Config()`` guarantees we observe the persisted state
    (not an in-memory manager that may have been updated without a flush).
    """
    import config as config_mod

    fresh = config_mod.Config()
    pm = fresh.get_playlist_manager()
    pl = pm.get_playlist(playlist_name)
    if not pl:
        return None
    return [p.name for p in pl.plugins]


def test_playlist_roundtrip_create_reorder_delete_persist(
    live_server, device_config_dev, flask_app, browser_page, tmp_path
):
    """Create playlist, add 3 plugins, reorder, delete, reload, assert persistence."""
    client = flask_app.test_client()
    playlist_name = f"journey-{uuid.uuid4().hex[:8]}"

    try:
        # ---------------------------------------------------------------
        # Step 2: Create a new playlist via POST and verify it was accepted.
        # ---------------------------------------------------------------
        resp = client.post(
            "/create_playlist",
            data=json.dumps(
                {
                    "playlist_name": playlist_name,
                    "start_time": "00:00",
                    "end_time": "23:59",
                }
            ),
            content_type="application/json",
        )
        assert (
            resp.status_code == 200
        ), f"create_playlist failed: {resp.status_code} {resp.data!r}"
        body = resp.get_json() or {}
        assert body.get("success") is True, f"create_playlist not success: {body}"

        # Verify playlist exists in backend state.
        pm = device_config_dev.get_playlist_manager()
        assert (
            pm.get_playlist(playlist_name) is not None
        ), "Newly created playlist not present in backend"

        # ---------------------------------------------------------------
        # Step 3: Add 3 plugins in a known order (seed directly; the
        # add-to-playlist form flow is exercised by other suites).
        # ---------------------------------------------------------------
        _seed_plugins(device_config_dev, playlist_name, _PLUGINS)
        expected_initial = [name for _, name in _PLUGINS]
        assert (
            _backend_instance_names(device_config_dev, playlist_name)
            == expected_initial
        ), "Seeded plugins not in expected order in backend"

        # ---------------------------------------------------------------
        # Navigate to /playlist and verify the initial order in the DOM.
        # ---------------------------------------------------------------
        page = browser_page
        rc = navigate_and_wait(page, live_server, "/playlist")

        dom_initial = _dom_instance_names(page, playlist_name)
        assert (
            dom_initial == expected_initial
        ), f"Initial DOM order mismatch: {dom_initial!r} != {expected_initial!r}"

        # ---------------------------------------------------------------
        # Step 4: Reorder — move the 3rd item to the top.
        # The UI exposes keyboard reorder on .plugin-item (ArrowUp/ArrowDown)
        # which fires the same /reorder_plugins POST as drag-and-drop.
        # From [A, B, C] -> ArrowUp on C -> [A, C, B] -> ArrowUp on C -> [C, A, B].
        # ---------------------------------------------------------------
        third_item_sel = (
            f".playlist-item[data-playlist-name='{playlist_name}'] "
            f".plugin-item[data-instance-name='{expected_initial[2]}']"
        )
        third_item = page.locator(third_item_sel)
        third_item.focus()
        third_item.press("ArrowUp")
        page.wait_for_timeout(300)
        third_item.press("ArrowUp")
        page.wait_for_timeout(500)  # allow fetch POST /reorder_plugins to complete

        expected_reordered = [
            expected_initial[2],
            expected_initial[0],
            expected_initial[1],
        ]
        dom_reordered = _dom_instance_names(page, playlist_name)
        assert dom_reordered == expected_reordered, (
            f"Post-reorder DOM order mismatch: {dom_reordered!r} != "
            f"{expected_reordered!r}"
        )

        # Poll briefly for backend to reflect reorder (fetch is async).
        backend_reordered = None
        for _ in range(20):
            backend_reordered = _backend_instance_names(
                device_config_dev, playlist_name
            )
            if backend_reordered == expected_reordered:
                break
            page.wait_for_timeout(100)
        assert backend_reordered == expected_reordered, (
            f"Backend did not persist reorder: {backend_reordered!r} != "
            f"{expected_reordered!r}"
        )

        # ---------------------------------------------------------------
        # Step 5: Delete the middle item via the UI delete-instance flow.
        # ---------------------------------------------------------------
        middle_name = expected_reordered[1]
        delete_btn = page.locator(
            f".playlist-item[data-playlist-name='{playlist_name}'] "
            f".plugin-item[data-instance-name='{middle_name}'] .delete-instance-btn"
        )
        delete_btn.wait_for(state="visible", timeout=5000)

        # Stub reload so the page stays introspectable after the fetch completes.
        page.evaluate("() => { window.location.reload = function() {}; }")

        delete_btn.click()
        confirm_modal = page.locator("#deleteInstanceModal")
        confirm_modal.wait_for(state="visible", timeout=3000)
        # Wait for the DELETE fetch to actually return so the resource listener
        # sees a clean 200 (not ERR_ABORTED from a stray page navigation).
        with page.expect_response(
            lambda r: "/delete_plugin_instance" in r.url and r.status == 200,
            timeout=5000,
        ):
            page.locator("#confirmDeleteInstanceBtn").click()

        # Poll until the DOM reflects deletion (fetch + DOM update is async).
        expected_after_delete = [
            expected_reordered[0],
            expected_reordered[2],
        ]
        for _ in range(30):
            # The delete handler calls location.reload(); the stub swallows it
            # but the execution context may still churn briefly — ignore
            # transient evaluate failures and rely on the backend check below
            # as the load-bearing assertion. (Mirrors mobile variant in
            # test_playlist_roundtrip_mobile.py.)
            try:
                dom_after_delete = _dom_instance_names(page, playlist_name)
                if dom_after_delete == expected_after_delete:
                    break
            except Exception:
                pass
            if (
                _backend_instance_names(device_config_dev, playlist_name)
                == expected_after_delete
            ):
                break
            page.wait_for_timeout(100)

        assert (
            _backend_instance_names(device_config_dev, playlist_name)
            == expected_after_delete
        ), (
            "Backend did not persist delete: "
            f"{_backend_instance_names(device_config_dev, playlist_name)!r} != "
            f"{expected_after_delete!r}"
        )

        # ---------------------------------------------------------------
        # Step 6/7: Reload the page and assert the post-reorder,
        # post-delete order persisted. This is the critical check that
        # catches silent "save was a no-op" bugs.
        # ---------------------------------------------------------------
        page.goto(f"{live_server}/playlist", wait_until="domcontentloaded")
        page.wait_for_selector("[data-page-shell]", timeout=10000)
        page.wait_for_timeout(300)

        dom_after_reload = _dom_instance_names(page, playlist_name)
        assert dom_after_reload == expected_after_delete, (
            f"Order did not persist through reload: {dom_after_reload!r} != "
            f"{expected_after_delete!r}"
        )

        rc.assert_no_errors(str(tmp_path), "playlist_roundtrip")

    finally:
        # Teardown: delete the test playlist regardless of outcome.
        try:
            client.delete(f"/delete_playlist/{playlist_name}")
        except Exception:
            pass
