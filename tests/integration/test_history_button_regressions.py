"""Regression tests for history page button actions.

JTN-330: Next pagination link must advance pages.
JTN-329: Clear All button must confirm and clear entries.
JTN-328: Delete buttons must confirm and remove items.
JTN-327: Display buttons must trigger redisplay action.

Root cause: inline boot script was not resilient to CSP or load-order
issues.  The fix moves endpoint URLs into data attributes on a hidden
DOM element so the page controller can read them without relying on
inline JS object literals.
"""

import json
import os

from PIL import Image

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_history(device_config, count, prefix="display_regression"):
    """Create *count* PNG files in the history directory and return filenames."""
    d = device_config.history_image_dir
    os.makedirs(d, exist_ok=True)
    names = []
    for i in range(count):
        name = f"{prefix}_{i:04d}.png"
        Image.new("RGB", (10, 10), "white").save(os.path.join(d, name))
        names.append(name)
    return names


def _seed_history_with_sidecar(device_config, count, prefix="display_sc"):
    """Create PNGs with matching JSON sidecar files."""
    d = device_config.history_image_dir
    os.makedirs(d, exist_ok=True)
    names = []
    for i in range(count):
        name = f"{prefix}_{i:04d}.png"
        Image.new("RGB", (10, 10), "white").save(os.path.join(d, name))
        sidecar = {"plugin_id": "test", "refresh_type": "Manual"}
        with open(
            os.path.join(d, name.replace(".png", ".json")), "w", encoding="utf-8"
        ) as fh:
            json.dump(sidecar, fh)
        names.append(name)
    return names


# ---------------------------------------------------------------------------
# JTN-330 — Next pagination link advances pages
# ---------------------------------------------------------------------------


class TestPaginationNext:
    """Verify the Next link renders as an <a> tag pointing to the correct page."""

    def test_next_link_present_on_first_page(self, client, device_config_dev):
        _seed_history(device_config_dev, 30, prefix="display_pnext")
        resp = client.get("/history?per_page=10")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "Page 1 of 3" in body
        assert "page=2" in body, "Next link must point to page=2"

    def test_next_link_returns_different_items(self, client, device_config_dev):
        names = _seed_history(device_config_dev, 20, prefix="display_pnextdiff")
        resp1 = client.get("/history?page=1&per_page=10")
        resp2 = client.get("/history?page=2&per_page=10")
        body1 = resp1.get_data(as_text=True)
        body2 = resp2.get_data(as_text=True)

        page1_items = {n for n in names if n in body1}
        page2_items = {n for n in names if n in body2}
        assert page1_items, "Page 1 must show some items"
        assert page2_items, "Page 2 must show some items"
        assert not page1_items & page2_items, "Pages must show disjoint items"

    def test_htmx_partial_returns_grid_fragment(self, client, device_config_dev):
        """HTMX pagination must return only the grid partial, not the full page."""
        _seed_history(device_config_dev, 15, prefix="display_htmx")
        resp = client.get(
            "/history?page=2&per_page=10",
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        # Partial must NOT include the full page shell (no <html>, no <head>)
        assert "<html" not in body.lower()
        # But must include the grid container
        assert 'id="history-grid-container"' in body

    def test_previous_link_on_page_two(self, client, device_config_dev):
        _seed_history(device_config_dev, 20, prefix="display_pprev")
        resp = client.get("/history?page=2&per_page=10")
        body = resp.get_data(as_text=True)
        assert "page=1" in body, "Previous link must point to page=1"

    def test_no_next_on_last_page(self, client, device_config_dev):
        _seed_history(device_config_dev, 15, prefix="display_plast")
        resp = client.get("/history?page=2&per_page=10")
        body = resp.get_data(as_text=True)
        # Next must be a disabled span, not a link
        assert "page=3" not in body


# ---------------------------------------------------------------------------
# JTN-329 — Clear All button confirms and clears entries
# ---------------------------------------------------------------------------


class TestClearAll:
    """Verify the Clear All endpoint removes all history images."""

    def test_clear_all_removes_all_pngs(self, client, device_config_dev):
        _seed_history(device_config_dev, 5, prefix="display_clr")
        d = device_config_dev.history_image_dir
        assert len([f for f in os.listdir(d) if f.endswith(".png")]) == 5

        resp = client.post("/history/clear")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get("success") is True
        assert "Cleared" in data.get("message", "")
        remaining = [f for f in os.listdir(d) if f.endswith(".png")]
        assert remaining == []

    def test_clear_all_removes_sidecars_too(self, client, device_config_dev):
        _seed_history_with_sidecar(device_config_dev, 3, prefix="display_clrsc")
        d = device_config_dev.history_image_dir
        assert len([f for f in os.listdir(d) if f.endswith(".json")]) == 3

        resp = client.post("/history/clear")
        assert resp.status_code == 200
        remaining_json = [f for f in os.listdir(d) if f.endswith(".json")]
        assert remaining_json == [], "Sidecar JSON files must also be cleared"

    def test_clear_all_modal_markup_present(self, client, device_config_dev):
        _seed_history(device_config_dev, 1, prefix="display_clrmod")
        resp = client.get("/history")
        body = resp.get_data(as_text=True)
        assert 'id="clearHistoryModal"' in body
        assert 'id="confirmClearHistoryBtn"' in body
        assert 'id="cancelClearHistoryBtn"' in body
        assert 'id="historyClearBtn"' in body

    def test_clear_on_empty_history_returns_success(self, client, device_config_dev):
        d = device_config_dev.history_image_dir
        os.makedirs(d, exist_ok=True)
        for f in os.listdir(d):
            os.remove(os.path.join(d, f))

        resp = client.post("/history/clear")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get("success") is True


# ---------------------------------------------------------------------------
# JTN-328 — Delete buttons confirm and remove items
# ---------------------------------------------------------------------------


class TestDeleteButton:
    """Verify the Delete endpoint removes specific files."""

    def test_delete_removes_target_file(self, client, device_config_dev):
        names = _seed_history(device_config_dev, 3, prefix="display_del")
        d = device_config_dev.history_image_dir
        target = names[1]
        assert os.path.exists(os.path.join(d, target))

        resp = client.post("/history/delete", json={"filename": target})
        assert resp.status_code == 200
        assert not os.path.exists(os.path.join(d, target))
        # Other files remain
        assert os.path.exists(os.path.join(d, names[0]))
        assert os.path.exists(os.path.join(d, names[2]))

    def test_delete_removes_matching_sidecar(self, client, device_config_dev):
        names = _seed_history_with_sidecar(device_config_dev, 2, prefix="display_delsc")
        d = device_config_dev.history_image_dir
        target = names[0]
        sidecar = target.replace(".png", ".json")
        assert os.path.exists(os.path.join(d, sidecar))

        resp = client.post("/history/delete", json={"filename": target})
        assert resp.status_code == 200
        assert not os.path.exists(os.path.join(d, target))
        assert not os.path.exists(
            os.path.join(d, sidecar)
        ), "Sidecar JSON must be deleted alongside the PNG"

    def test_delete_modal_markup_present(self, client, device_config_dev):
        _seed_history(device_config_dev, 1, prefix="display_delmod")
        resp = client.get("/history")
        body = resp.get_data(as_text=True)
        assert 'id="deleteHistoryModal"' in body
        assert 'id="confirmDeleteHistoryBtn"' in body
        assert 'id="cancelDeleteHistoryBtn"' in body

    def test_delete_buttons_carry_data_attrs(self, client, device_config_dev):
        names = _seed_history(device_config_dev, 1, prefix="display_delattr")
        resp = client.get("/history")
        body = resp.get_data(as_text=True)
        assert 'data-history-action="delete"' in body
        assert f'data-filename="{names[0]}"' in body

    def test_delete_nonexistent_returns_404(self, client):
        resp = client.post("/history/delete", json={"filename": "nonexistent.png"})
        assert resp.status_code == 404

    def test_delete_missing_filename_returns_400(self, client):
        resp = client.post("/history/delete", json={})
        assert resp.status_code == 400

    def test_delete_path_traversal_returns_400(self, client):
        resp = client.post("/history/delete", json={"filename": "../../etc/passwd"})
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# JTN-327 — Display buttons trigger redisplay
# ---------------------------------------------------------------------------


class TestDisplayButton:
    """Verify the Display (redisplay) endpoint works end-to-end."""

    def test_redisplay_returns_success(self, client, device_config_dev):
        names = _seed_history(device_config_dev, 1, prefix="display_redisp")
        resp = client.post("/history/redisplay", json={"filename": names[0]})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get("success") is True

    def test_display_buttons_carry_data_attrs(self, client, device_config_dev):
        names = _seed_history(device_config_dev, 1, prefix="display_dispattr")
        resp = client.get("/history")
        body = resp.get_data(as_text=True)
        assert 'data-history-action="display"' in body
        assert f'data-filename="{names[0]}"' in body

    def test_redisplay_missing_filename_returns_400(self, client):
        resp = client.post("/history/redisplay", json={})
        assert resp.status_code == 400

    def test_redisplay_nonexistent_file_returns_404(self, client):
        resp = client.post("/history/redisplay", json={"filename": "nonexistent.png"})
        assert resp.status_code in (400, 404)

    def test_redisplay_path_traversal_returns_400(self, client):
        resp = client.post("/history/redisplay", json={"filename": "../../etc/passwd"})
        assert resp.status_code == 400

    def test_redisplay_invalid_json_returns_400(self, client):
        resp = client.post(
            "/history/redisplay",
            data="not json",
            content_type="application/json",
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Boot config wiring — data attributes approach
# ---------------------------------------------------------------------------


class TestBootConfig:
    """Verify the boot data element carries all required endpoint URLs."""

    def test_boot_data_element_present(self, client):
        resp = client.get("/history")
        body = resp.get_data(as_text=True)
        assert 'id="historyBootData"' in body

    def test_boot_data_has_clear_url(self, client):
        resp = client.get("/history")
        body = resp.get_data(as_text=True)
        assert 'data-clear-url="/history/clear"' in body

    def test_boot_data_has_delete_url(self, client):
        resp = client.get("/history")
        body = resp.get_data(as_text=True)
        assert 'data-delete-url="/history/delete"' in body

    def test_boot_data_has_redisplay_url(self, client):
        resp = client.get("/history")
        body = resp.get_data(as_text=True)
        assert 'data-redisplay-url="/history/redisplay"' in body

    def test_boot_data_has_storage_url(self, client):
        resp = client.get("/history")
        body = resp.get_data(as_text=True)
        assert 'data-storage-url="/history/storage"' in body

    def test_page_controller_invoked_in_script(self, client):
        resp = client.get("/history")
        body = resp.get_data(as_text=True)
        assert "InkyPiHistoryPage" in body
        assert ".create(" in body
        assert ".init()" in body
