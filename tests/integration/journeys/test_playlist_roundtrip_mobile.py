# pyright: reportMissingImports=false
"""Mobile-viewport playlist round-trip journey test (JTN-729, epic JTN-719).

Mirrors the desktop playlist round-trip journey (JTN-721) but on the
``mobile_page`` (360x800) fixture. Adds two mobile-specific assertions:

- After each interaction, the targeted element's bounding rect is
  at least 44x44 CSS px (touch-target minimum).
- The playlist container never horizontally overflows the viewport.
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

_PLUGINS = [
    ("clock", "Step1 Clock"),
    ("clock", "Step2 Clock"),
    ("clock", "Step3 Clock"),
]

_MOBILE_MIN_TOUCH = 44  # CSS px, per WCAG 2.5.5 / Apple HIG touch-target minimum.


def _seed_plugins(device_config, playlist_name, instances):
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
    import config as config_mod

    fresh = config_mod.Config()
    pm = fresh.get_playlist_manager()
    pl = pm.get_playlist(playlist_name)
    if not pl:
        return None
    return [p.name for p in pl.plugins]


def _assert_touch_target(locator, label):
    """Assert the locator's bounding rect meets 44x44 CSS px minimum."""
    box = locator.bounding_box()
    assert box is not None, f"{label}: could not resolve bounding box"
    assert box["width"] >= _MOBILE_MIN_TOUCH and box["height"] >= _MOBILE_MIN_TOUCH, (
        f"{label}: touch target {box['width']:.1f}x{box['height']:.1f} "
        f"< {_MOBILE_MIN_TOUCH}x{_MOBILE_MIN_TOUCH} CSS px"
    )


def _assert_no_horizontal_overflow(page, playlist_name, label):
    """Assert the playlist card does not scroll horizontally past viewport."""
    overflow = page.evaluate(
        """(pn) => {
            const card = Array.from(document.querySelectorAll('.playlist-item'))
              .find(el => el.getAttribute('data-playlist-name') === pn);
            if (!card) return null;
            return {
              scrollWidth: card.scrollWidth,
              clientWidth: card.clientWidth,
              viewportWidth: window.innerWidth,
              rectRight: card.getBoundingClientRect().right,
            };
        }""",
        playlist_name,
    )
    assert overflow is not None, f"{label}: playlist card not found"
    # A 1px slack absorbs subpixel rounding in headless Chromium.
    assert overflow["scrollWidth"] <= overflow["clientWidth"] + 1, (
        f"{label}: playlist card horizontally overflows: "
        f"scrollWidth={overflow['scrollWidth']} > clientWidth={overflow['clientWidth']}"
    )
    assert overflow["rectRight"] <= overflow["viewportWidth"] + 1, (
        f"{label}: playlist card extends past viewport: "
        f"right={overflow['rectRight']} > viewport={overflow['viewportWidth']}"
    )


def test_playlist_roundtrip_mobile_create_reorder_delete_persist(
    live_server, device_config_dev, flask_app, mobile_page, tmp_path
):
    """Mobile viewport: create, reorder, delete, reload; assert persistence +
    touch-target minimums + no horizontal overflow at each step."""
    client = flask_app.test_client()
    playlist_name = f"journey-m-{uuid.uuid4().hex[:8]}"

    try:
        # Step 2: create playlist via POST.
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

        pm = device_config_dev.get_playlist_manager()
        assert (
            pm.get_playlist(playlist_name) is not None
        ), "Newly created playlist not present in backend"

        # Step 3: seed 3 plugins.
        _seed_plugins(device_config_dev, playlist_name, _PLUGINS)
        expected_initial = [name for _, name in _PLUGINS]
        assert (
            _backend_instance_names(device_config_dev, playlist_name)
            == expected_initial
        ), "Seeded plugins not in expected order in backend"

        page = mobile_page
        rc = navigate_and_wait(page, live_server, "/playlist")

        # On mobile the playlist.js UI collapses non-active cards. Expand our
        # test card via the toggle button so plugin items are interactable.
        toggle = page.locator(
            f".playlist-item[data-playlist-name='{playlist_name}'] "
            "[data-playlist-toggle]"
        )
        toggle.wait_for(state="visible", timeout=5000)
        _assert_touch_target(toggle, "playlist-toggle-button")
        if toggle.get_attribute("aria-expanded") != "true":
            toggle.click()
            page.wait_for_timeout(200)

        dom_initial = _dom_instance_names(page, playlist_name)
        assert (
            dom_initial == expected_initial
        ), f"Initial DOM order mismatch: {dom_initial!r} != {expected_initial!r}"
        _assert_no_horizontal_overflow(page, playlist_name, "initial load")

        # Step 4: reorder via keyboard (ArrowUp twice on 3rd item -> [C, A, B]).
        third_item_sel = (
            f".playlist-item[data-playlist-name='{playlist_name}'] "
            f".plugin-item[data-instance-name='{expected_initial[2]}']"
        )
        third_item = page.locator(third_item_sel)
        third_item.scroll_into_view_if_needed()
        _assert_touch_target(third_item, "plugin-item (reorder target)")
        third_item.focus()
        third_item.press("ArrowUp")
        page.wait_for_timeout(300)
        third_item.press("ArrowUp")
        page.wait_for_timeout(500)

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
        _assert_no_horizontal_overflow(page, playlist_name, "after reorder")

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

        # Step 5: delete middle item via the UI.
        middle_name = expected_reordered[1]
        delete_btn = page.locator(
            f".playlist-item[data-playlist-name='{playlist_name}'] "
            f".plugin-item[data-instance-name='{middle_name}'] .delete-instance-btn"
        )
        delete_btn.wait_for(state="visible", timeout=5000)
        delete_btn.scroll_into_view_if_needed()
        _assert_touch_target(delete_btn, "delete-instance-btn")

        page.evaluate("() => { window.location.reload = function() {}; }")

        delete_btn.click()
        confirm_modal = page.locator("#deleteInstanceModal")
        confirm_modal.wait_for(state="visible", timeout=3000)
        confirm_btn = page.locator("#confirmDeleteInstanceBtn")
        _assert_touch_target(confirm_btn, "confirmDeleteInstanceBtn")
        with page.expect_response(
            lambda r: "/delete_plugin_instance" in r.url and r.status == 200,
            timeout=5000,
        ):
            confirm_btn.click()

        expected_after_delete = [expected_reordered[0], expected_reordered[2]]
        for _ in range(30):
            # The delete handler calls location.reload(); the stub swallows it
            # but execution context may still churn briefly — ignore transient
            # evaluate failures and rely on the backend check.
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

        # Step 6/7: reload and assert persisted order.
        page.goto(f"{live_server}/playlist", wait_until="domcontentloaded")
        page.wait_for_selector("[data-page-shell]", timeout=10000)
        page.wait_for_timeout(300)

        # Re-expand the test card on mobile after reload.
        toggle_reload = page.locator(
            f".playlist-item[data-playlist-name='{playlist_name}'] "
            "[data-playlist-toggle]"
        )
        toggle_reload.wait_for(state="visible", timeout=5000)
        if toggle_reload.get_attribute("aria-expanded") != "true":
            toggle_reload.click()
            page.wait_for_timeout(200)

        dom_after_reload = _dom_instance_names(page, playlist_name)
        assert dom_after_reload == expected_after_delete, (
            f"Order did not persist through reload: {dom_after_reload!r} != "
            f"{expected_after_delete!r}"
        )
        _assert_no_horizontal_overflow(page, playlist_name, "after reload")

        rc.assert_no_errors(str(tmp_path), "playlist_roundtrip_mobile")

    finally:
        try:
            client.delete(f"/delete_playlist/{playlist_name}")
        except Exception:
            pass
