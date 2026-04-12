"""Static and integration tests for history page action bugs.

JTN-305: Display button must call the redisplay endpoint.
JTN-306: Delete button must open a confirm modal and call the delete endpoint.
JTN-307: Clear All button must open a confirm modal and call the clear endpoint.
JTN-308: Pagination Next link must have a valid href to the next page.
"""

import os

from PIL import Image

# ---------------------------------------------------------------------------
# JTN-305 — Display button wired to redisplay endpoint
# ---------------------------------------------------------------------------


def test_history_page_js_redisplay_function_exists(client):
    """JTN-305: history_page.js must define an async redisplay function."""
    resp = client.get("/static/scripts/history_page.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    assert (
        "async function redisplay(" in js
    ), "history_page.js must define async function redisplay(filename, button)"


def test_history_page_js_redisplay_posts_to_config_url(client):
    """JTN-305: redisplay must POST to config.redisplayUrl with filename in body."""
    resp = client.get("/static/scripts/history_page.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    assert (
        "config.redisplayUrl" in js
    ), "redisplay must POST to config.redisplayUrl (not a hardcoded path)"
    assert 'method: "POST"' in js, "redisplay must use HTTP POST"
    assert (
        "JSON.stringify({ filename })" in js
    ), "redisplay must send {filename} as JSON body"


def test_history_page_js_display_action_bound_via_delegation(client):
    """JTN-305: click handler must delegate to [data-history-action='display'] buttons."""
    resp = client.get("/static/scripts/history_page.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    assert (
        "data-history-action" in js
    ), "JS must select buttons via data-history-action attribute"
    assert (
        'action === "display"' in js
    ), "delegated handler must check action === 'display' to call redisplay"
    assert (
        "redisplay(filename, actionButton)" in js
    ), "must pass filename and button reference to redisplay()"


def test_history_template_display_buttons_have_data_attrs(client, device_config_dev):
    """JTN-305: rendered history page must include data-history-action=display buttons."""
    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    fname = "display_20250201_000000.png"
    Image.new("RGB", (10, 10), "white").save(os.path.join(d, fname))

    resp = client.get("/history")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    assert (
        'data-history-action="display"' in body
    ), 'Display buttons must carry data-history-action="display"'
    assert (
        f'data-filename="{fname}"' in body
    ), "Display buttons must carry the filename in data-filename"


def test_history_template_boot_provides_redisplay_url(client):
    """JTN-305: inline boot script must pass redisplayUrl to the page controller."""
    resp = client.get("/history")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    assert (
        "redisplayUrl" in body
    ), "Boot script must set redisplayUrl so the JS can POST to the correct endpoint"
    assert (
        "/history/redisplay" in body
    ), "redisplayUrl must resolve to /history/redisplay"


def test_history_redisplay_endpoint_accepts_post(client, device_config_dev):
    """JTN-305: /history/redisplay must accept POST with filename and succeed."""
    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    fname = "display_20250201_010000.png"
    Image.new("RGB", (10, 10), "white").save(os.path.join(d, fname))

    resp = client.post("/history/redisplay", json={"filename": fname})
    assert (
        resp.status_code == 200
    ), f"/history/redisplay returned {resp.status_code}; expected 200"
    data = resp.get_json()
    assert data.get("success") is True


# ---------------------------------------------------------------------------
# JTN-306 — Delete button wired to delete endpoint via confirmation modal
# ---------------------------------------------------------------------------


def test_history_page_js_open_delete_modal_function(client):
    """JTN-306: history_page.js must define openDeleteModal to show confirmation."""
    resp = client.get("/static/scripts/history_page.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    assert (
        "function openDeleteModal(" in js
    ), "openDeleteModal function must exist to present the delete confirmation"
    assert (
        "deleteHistoryModal" in js
    ), "modal must reference the #deleteHistoryModal element"


def test_history_page_js_confirm_delete_posts_to_config_url(client):
    """JTN-306: confirmDelete must POST filename to config.deleteUrl."""
    resp = client.get("/static/scripts/history_page.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    assert (
        "async function confirmDelete(" in js
    ), "confirmDelete async function must exist"
    assert (
        "config.deleteUrl" in js
    ), "confirmDelete must POST to config.deleteUrl (not a hardcoded path)"
    assert (
        "state.pendingDelete" in js
    ), "confirmDelete must read the filename from state.pendingDelete"


def test_history_page_js_delete_action_bound_via_delegation(client):
    """JTN-306: delegated handler must wire delete action to openDeleteModal."""
    resp = client.get("/static/scripts/history_page.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    assert (
        'action === "delete"' in js
    ), "delegated click handler must branch on action === 'delete'"
    assert (
        "openDeleteModal(filename)" in js
    ), "delete action must call openDeleteModal with the filename"


def test_history_template_delete_buttons_have_data_attrs(client, device_config_dev):
    """JTN-306: rendered history page must include data-history-action=delete buttons."""
    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    fname = "display_20250201_020000.png"
    Image.new("RGB", (10, 10), "white").save(os.path.join(d, fname))

    resp = client.get("/history")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    assert (
        'data-history-action="delete"' in body
    ), 'Delete buttons must carry data-history-action="delete"'
    assert f'data-filename="{fname}"' in body


def test_history_template_boot_provides_delete_url(client):
    """JTN-306: boot script must expose deleteUrl to the JS controller."""
    resp = client.get("/history")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    assert "deleteUrl" in body, "Boot script must set deleteUrl"
    assert "/history/delete" in body, "deleteUrl must resolve to /history/delete"


def test_history_template_includes_delete_modal(client, device_config_dev):
    """JTN-306: rendered page must include the delete confirmation modal markup."""
    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    Image.new("RGB", (10, 10), "white").save(
        os.path.join(d, "display_20250201_030000.png")
    )

    resp = client.get("/history")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    assert (
        'id="deleteHistoryModal"' in body
    ), "Delete confirmation modal must be present"
    assert 'id="confirmDeleteHistoryBtn"' in body, "Confirm delete button must exist"
    assert 'id="cancelDeleteHistoryBtn"' in body, "Cancel delete button must exist"


def test_history_delete_endpoint_removes_file(client, device_config_dev):
    """JTN-306: POST to /history/delete removes the target file."""
    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    fname = "display_20250201_040000.png"
    fpath = os.path.join(d, fname)
    Image.new("RGB", (10, 10), "white").save(fpath)
    assert os.path.exists(fpath)

    resp = client.post("/history/delete", json={"filename": fname})
    assert resp.status_code == 200
    assert not os.path.exists(
        fpath
    ), "File must be deleted after POST to /history/delete"


# ---------------------------------------------------------------------------
# JTN-307 — Clear All button wired to clear endpoint via confirmation modal
# ---------------------------------------------------------------------------


def test_history_page_js_open_clear_modal_function(client):
    """JTN-307: history_page.js must define openClearModal."""
    resp = client.get("/static/scripts/history_page.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    assert (
        "function openClearModal(" in js
    ), "openClearModal function must exist to present the clear confirmation"
    assert (
        "clearHistoryModal" in js
    ), "modal must reference the #clearHistoryModal element"


def test_history_page_js_confirm_clear_posts_to_config_url(client):
    """JTN-307: confirmClear must POST to config.clearUrl."""
    resp = client.get("/static/scripts/history_page.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    assert (
        "async function confirmClear(" in js
    ), "confirmClear async function must exist"
    assert "config.clearUrl" in js, "confirmClear must POST to config.clearUrl"
    assert 'method: "POST"' in js, "confirmClear must use HTTP POST"


def test_history_page_js_clear_btn_bound_to_open_modal(client):
    """JTN-307: #historyClearBtn click must open the clear confirmation modal."""
    resp = client.get("/static/scripts/history_page.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    assert (
        '"historyClearBtn"' in js or "'historyClearBtn'" in js
    ), "bindActions must reference historyClearBtn"
    assert (
        "openClearModal" in js
    ), "historyClearBtn click handler must call openClearModal"


def test_history_template_boot_provides_clear_url(client):
    """JTN-307: boot script must expose clearUrl to the JS controller."""
    resp = client.get("/history")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    assert "clearUrl" in body, "Boot script must set clearUrl"
    assert "/history/clear" in body, "clearUrl must resolve to /history/clear"


def test_history_template_includes_clear_all_modal(client, device_config_dev):
    """JTN-307: rendered page must include the clear-all confirmation modal markup."""
    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    Image.new("RGB", (10, 10), "white").save(
        os.path.join(d, "display_20250201_050000.png")
    )

    resp = client.get("/history")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    assert 'id="clearHistoryModal"' in body, "Clear-all modal must be in the DOM"
    assert 'id="confirmClearHistoryBtn"' in body, "Confirm clear button must exist"
    assert 'id="cancelClearHistoryBtn"' in body, "Cancel clear button must exist"
    assert 'id="historyClearBtn"' in body, "Clear All trigger button must exist"


def test_history_clear_endpoint_removes_all_files(client, device_config_dev):
    """JTN-307: POST to /history/clear removes all history images."""
    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    for i in range(3):
        Image.new("RGB", (10, 10), "white").save(
            os.path.join(d, f"display_20250201_06000{i}.png")
        )
    assert len([f for f in os.listdir(d) if f.endswith(".png")]) == 3

    resp = client.post("/history/clear")
    assert resp.status_code == 200
    remaining = [f for f in os.listdir(d) if f.endswith(".png")]
    assert remaining == [], f"Expected no PNGs after clear, found: {remaining}"


# ---------------------------------------------------------------------------
# JTN-308 — Pagination Next link navigates to page + 1
# ---------------------------------------------------------------------------


def test_history_template_next_link_is_anchor_with_href(client, device_config_dev):
    """JTN-308: Next pagination element must be an <a> tag with a valid href."""
    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    # Create enough images to trigger pagination (per_page=10, need >10)
    for i in range(15):
        Image.new("RGB", (10, 10), "white").save(
            os.path.join(d, f"display_20250201_07{i:04d}.png")
        )

    resp = client.get("/history?per_page=10")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    assert "Next" in body, "Next should appear when there are multiple pages"

    # The Next element must be an anchor tag, not a disabled span
    next_idx = body.find(">Next<")
    assert next_idx != -1, "Next link text must be present"

    # Walk backwards from ">Next<" to find the opening tag
    tag_start = body.rfind("<", 0, next_idx)
    opening_tag = body[tag_start:next_idx]

    assert opening_tag.startswith(
        "<a "
    ), f"Next must be rendered as an <a> tag, got: {opening_tag!r}"
    assert (
        "href=" in opening_tag
    ), f"Next <a> tag must include an href attribute, got: {opening_tag!r}"


def test_history_template_next_href_advances_page(client, device_config_dev):
    """JTN-308: Next link href must point to page=N+1 with same per_page."""
    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    for i in range(20):
        Image.new("RGB", (10, 10), "white").save(
            os.path.join(d, f"display_20250201_08{i:04d}.png")
        )

    resp = client.get("/history?page=1&per_page=10")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    assert "page=2" in body, "On page 1 the Next link href must contain page=2"


def test_history_template_next_href_on_middle_page(client, device_config_dev):
    """JTN-308: On page 2 of 3, Next href must point to page=3."""
    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    for i in range(30):
        Image.new("RGB", (10, 10), "white").save(
            os.path.join(d, f"display_20250201_09{i:04d}.png")
        )

    resp = client.get("/history?page=2&per_page=10")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    assert "page=3" in body, "On page 2 the Next link href must contain page=3"


def test_history_template_next_not_rendered_on_last_page(client, device_config_dev):
    """JTN-308: On the last page, Next must be a disabled span (no href)."""
    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    for i in range(15):
        Image.new("RGB", (10, 10), "white").save(
            os.path.join(d, f"display_20250201_10{i:04d}.png")
        )

    # 15 items, per_page=10 → 2 pages. On page 2, Next must be disabled.
    resp = client.get("/history?page=2&per_page=10")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    # The "Next" text must exist (as disabled span) but must not be a link
    assert "Next" in body
    # There must be no href pointing forward beyond the last page
    assert (
        "page=3" not in body
    ), "Next must not link to page=3 when page 2 is the last page"


def test_history_next_page_loads_different_items(client, device_config_dev):
    """JTN-308: Following the Next link must serve a different set of items."""
    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    names = [f"display_20250201_11{i:04d}.png" for i in range(20)]
    for name in names:
        Image.new("RGB", (10, 10), "white").save(os.path.join(d, name))

    resp1 = client.get("/history?page=1&per_page=10")
    resp2 = client.get("/history?page=2&per_page=10")

    assert resp1.status_code == 200
    assert resp2.status_code == 200

    body1 = resp1.get_data(as_text=True)
    body2 = resp2.get_data(as_text=True)

    # The two pages must not show identical content
    # Extract the grid section (filenames present) from each
    grid_names_p1 = {n for n in names if n in body1}
    grid_names_p2 = {n for n in names if n in body2}

    # Pages must be disjoint (no file shown on both pages)
    overlap = grid_names_p1 & grid_names_p2
    assert (
        not overlap
    ), f"Pages 1 and 2 share items, suggesting pagination is broken: {overlap}"


# ---------------------------------------------------------------------------
# Boot config wiring — all four URLs must be present in the boot object
# ---------------------------------------------------------------------------


def test_history_template_boot_config_has_all_four_urls(client):
    """JTN-305/306/307/308: all required URL keys must be in the boot config."""
    resp = client.get("/history")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    for key in ("redisplayUrl", "deleteUrl", "clearUrl", "storageUrl"):
        assert (
            key in body
        ), f"Boot config must include '{key}' so JS actions can reach their endpoints"


def test_history_template_boot_invokes_page_controller(client):
    """JTN-305/306/307: page must call InkyPiHistoryPage.create(...).init()."""
    resp = client.get("/history")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    assert "InkyPiHistoryPage" in body, "Boot script must reference InkyPiHistoryPage"
    assert ".create(" in body, "Boot script must call .create() to instantiate the page"
    assert ".init()" in body, "Boot script must call .init() to wire up event handlers"


def test_history_page_js_rebinds_images_after_htmx_swap(client):
    """JTN-330: history_page.js must listen for htmx:afterSettle to rebind
    image skeleton handlers after HTMX swaps the grid."""
    resp = client.get("/static/scripts/history_page.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    assert (
        "htmx:afterSettle" in js
    ), "history_page.js must listen for htmx:afterSettle to rebind images after swap"
    assert (
        "bindImages" in js
    ), "htmx:afterSettle handler must call bindImages to rebind skeleton handlers"
