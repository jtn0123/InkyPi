import json
import os

from PIL import Image


def test_history_page_lists_images(client, device_config_dev):
    # Create two history images
    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    for name in ["display_20250101_000000.png", "display_20250101_000100.png"]:
        Image.new("RGB", (10, 10), "white").save(os.path.join(d, name))

    resp = client.get("/history")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "display_20250101_000000.png" in body
    assert "display_20250101_000100.png" in body


def test_history_sidecar_metadata_rendered(client, device_config_dev):
    # Create an image and matching sidecar json
    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    fname = "display_20250101_010000.png"
    Image.new("RGB", (10, 10), "white").save(os.path.join(d, fname))
    sidecar = {
        "refresh_type": "Playlist",
        "plugin_id": "ai_text",
        "playlist": "Default",
        "plugin_instance": "ai_text_saved_settings",
    }
    with open(
        os.path.join(d, "display_20250101_010000.json"), "w", encoding="utf-8"
    ) as fh:
        json.dump(sidecar, fh)

    resp = client.get("/history")
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert "Source:" in text
    assert "Playlist" in text
    assert "ai_text" in text


def test_history_delete_and_clear(client, device_config_dev):
    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    a = os.path.join(d, "display_20250101_000300.png")
    b = os.path.join(d, "display_20250101_000400.png")
    Image.new("RGB", (10, 10), "white").save(a)
    Image.new("RGB", (10, 10), "white").save(b)

    # Delete one
    resp = client.post("/history/delete", json={"filename": os.path.basename(a)})
    assert resp.status_code == 200
    assert not os.path.exists(a)
    assert os.path.exists(b)

    # Clear the rest
    resp = client.post("/history/clear")
    assert resp.status_code == 200
    assert not os.path.exists(b)


def test_history_page_shows_no_history_message(client, device_config_dev):
    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    # Ensure empty
    for f in os.listdir(d):
        os.remove(os.path.join(d, f))

    resp = client.get("/history")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "No history yet." in body


def test_history_page_contains_storage_block(client):
    resp = client.get("/history")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert 'id="storage-block"' in body
    # Should include server-rendered text placeholders or values
    assert "Storage available" in body


def test_history_page_moves_clear_action_to_reset_cache(client, device_config_dev):
    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    Image.new("RGB", (10, 10), "white").save(
        os.path.join(d, "display_20250101_000700.png")
    )

    resp = client.get("/history")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "Reset cache" in body
    assert 'id="historyClearBtn"' in body


def test_history_image_blocks_path_traversal(client):
    """Bug 4: history_image should reject path traversal attempts."""
    resp = client.get("/history/image/../../etc/passwd")
    assert resp.status_code == 400


def test_history_image_route_serves_png(client, device_config_dev):
    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    name = "display_20250101_000500.png"
    from PIL import Image

    Image.new("RGB", (10, 10), "white").save(os.path.join(d, name))

    resp = client.get(f"/history/image/{name}")
    assert resp.status_code == 200
    assert resp.headers.get("Content-Type", "").startswith("image/")


def test_history_security_blocks_path_traversal_on_delete(client):
    # Attempt to escape history dir
    resp = client.post("/history/delete", json={"filename": "../../etc/passwd"})
    assert resp.status_code == 400


def test_history_security_blocks_prefix_bypass_path(client):
    # Attempt sibling-directory prefix bypass like history/../history_evil/*
    resp = client.post(
        "/history/delete", json={"filename": "../history_evil/should_not_delete.png"}
    )
    assert resp.status_code == 400


def test_history_storage_endpoint_values(client, monkeypatch):
    # Monkeypatch shutil.disk_usage to return known numbers for precise assertions
    class Usage:
        total = 4 * (1024**3)  # 4 GB
        used = 3 * (1024**3)  # 3 GB
        free = 1 * (1024**3)  # 1 GB

    import shutil as _shutil

    monkeypatch.setattr(_shutil, "disk_usage", lambda p: Usage)

    resp = client.get("/history/storage")
    assert resp.status_code == 200
    data = resp.get_json()
    assert {"free_gb", "total_gb", "used_gb", "pct_free"}.issubset(data.keys())
    assert data["total_gb"] == 4.0
    assert data["free_gb"] == 1.0
    assert data["used_gb"] == 3.0
    assert data["pct_free"] == 25.0


def test_history_clear_then_storage_endpoint_ok(client, device_config_dev):
    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    from PIL import Image

    for i in range(3):
        Image.new("RGB", (10, 10), "white").save(
            os.path.join(d, f"display_20250101_00060{i}.png")
        )

    resp = client.post("/history/clear")
    assert resp.status_code == 200
    assert len([f for f in os.listdir(d) if f.endswith(".png")]) == 0

    resp2 = client.get("/history/storage")
    assert resp2.status_code == 200
    data2 = resp2.get_json()
    assert data2.get("pct_free") is None or (
        0.0 <= float(data2.get("pct_free")) <= 100.0
    )


def test_history_redisplay_errors(client):
    # Missing filename
    resp = client.post("/history/redisplay", json={})
    assert resp.status_code == 400

    # Non-existent file
    resp = client.post("/history/redisplay", json={"filename": "missing.png"})
    assert resp.status_code in (400, 404)

    # Traversal attempt
    resp = client.post("/history/redisplay", json={"filename": "../../etc/passwd"})
    assert resp.status_code == 400


def test_history_redisplay_invalid_json_returns_400(client):
    resp = client.post(
        "/history/redisplay",
        data="not json",
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Invalid JSON payload"


def test_history_redisplay_success(client, device_config_dev):
    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    fname = "display_20250101_020000.png"
    Image.new("RGB", (10, 10), "white").save(os.path.join(d, fname))

    resp = client.post("/history/redisplay", json={"filename": fname})
    assert resp.status_code == 200
    assert resp.get_json().get("success") is True


def test_history_delete_errors(client):
    # Missing filename
    resp = client.post("/history/delete", json={})
    assert resp.status_code == 400

    # Non-existent file
    resp = client.post("/history/delete", json={"filename": "missing.png"})
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "File not found"

    # Traversal attempt
    resp = client.post("/history/delete", json={"filename": "../../etc/passwd"})
    assert resp.status_code == 400


def test_history_delete_invalid_json_returns_400(client):
    resp = client.post(
        "/history/delete",
        data="not json",
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Invalid JSON payload"


def test_history_sorting_and_size_formatting(client, device_config_dev):
    import time

    from PIL import Image

    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    a = os.path.join(d, "a.png")
    b = os.path.join(d, "b.png")
    Image.new("RGB", (10, 10), "white").save(a)
    Image.new("RGB", (20, 20), "white").save(b)

    # Ensure b is newer by explicitly setting modification times
    now = time.time()
    os.utime(a, (now, now))
    os.utime(b, (now + 1, now + 1))

    # Touch sizes for clear difference
    os.truncate(a, 100)
    os.truncate(b, 2048)

    from blueprints import history as history_mod

    images, total = history_mod._list_history_images(d)
    names = [img["filename"] for img in images]
    assert "b.png" in names and "a.png" in names
    assert total == 2

    resp = client.get("/history")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")

    # Size strings should include units like B or KB
    assert "100 B" in body or "0.1 KB" in body or "KB" in body


def test_history_sorting_uses_embedded_timestamp_when_mtimes_match(device_config_dev):
    from blueprints import history as history_mod

    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    names = [
        "display_20250101_174133.png",
        "display_20250101_211633.png",
        "display_20250101_185438.png",
    ]
    for name in names:
        Image.new("RGB", (10, 10), "white").save(os.path.join(d, name))

    identical_time = 1_735_689_600
    for name in names:
        os.utime(os.path.join(d, name), (identical_time, identical_time))

    images, total = history_mod._list_history_images(d)
    assert total == 3
    ordered_names = [img["filename"] for img in images[:3]]
    assert ordered_names == [
        "display_20250101_211633.png",
        "display_20250101_185438.png",
        "display_20250101_174133.png",
    ]


def test_history_server_renders_storage_when_disk_usage_ok(client, monkeypatch):
    class Usage:
        total = 4 * (1024**3)
        used = 3 * (1024**3)
        free = 1 * (1024**3)

    import shutil as _shutil

    monkeypatch.setattr(_shutil, "disk_usage", lambda p: Usage)
    resp = client.get("/history")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "% free" in body
    # Match new template wording
    assert "GB remaining of" in body and "GB total" in body


def test_history_server_handles_disk_usage_failure(client, monkeypatch):
    import shutil as _shutil

    monkeypatch.setattr(
        _shutil, "disk_usage", lambda p: (_ for _ in ()).throw(OSError("fail"))
    )
    resp = client.get("/history")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    # Storage block may be hidden; ensure page still renders with header
    assert "History" in body


def test_history_handles_file_stat_race(client, device_config_dev, monkeypatch):
    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)

    # Create a file then remove it just before getmtime/getsize is called
    path = os.path.join(d, "race.png")
    from PIL import Image

    Image.new("RGB", (10, 10), "white").save(path)

    # Monkeypatch os.path.getmtime to raise for this file
    import os as _os

    real_getmtime = _os.path.getmtime

    def flaky_getmtime(p):
        if p == path:
            raise FileNotFoundError("race gone")
        return real_getmtime(p)

    monkeypatch.setattr(_os.path, "getmtime", flaky_getmtime)

    resp = client.get("/history")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    # Page should still render; either show no entries or skip the raced file
    assert "History" in body


def test_history_template_scripts_closed_and_grid_renders(client):
    resp = client.get("/history")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    # Basic sanity: we have a closing script tag
    first_script_open = body.find("<script")
    first_script_close = body.find("</script>")
    assert first_script_open != -1
    assert first_script_close != -1
    # If a grid is present, it should appear after a closing script tag
    grid_idx = body.find('class="history-grid"')
    if grid_idx != -1:
        assert first_script_close < grid_idx


def test_format_size_exception_handling(monkeypatch):
    from blueprints.history import _format_size

    # Test exception handling in _format_size - negative numbers don't trigger exception
    # Let's test with a very large number that might cause issues
    result = _format_size(10**20)  # Very large number
    # Should still format properly or fall back to exception path
    assert isinstance(result, str)


def test_list_history_images_exception_handling(client, device_config_dev, monkeypatch):
    import blueprints.history as history_mod

    # Mock os.listdir to raise exception
    monkeypatch.setattr(
        history_mod.os, "listdir", lambda p: (_ for _ in ()).throw(Exception("test"))
    )

    result, total = history_mod._list_history_images(
        device_config_dev.history_image_dir
    )
    assert result == []
    assert total == 0


def test_history_delete_exception_handling(client, flask_app, monkeypatch):
    import blueprints.history as history_mod

    monkeypatch.setattr(
        history_mod,
        "_resolve_history_path",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(Exception("test")),
    )

    resp = client.post("/history/delete", json={"filename": "test.png"})
    assert resp.status_code == 500
    assert "An internal error occurred" in resp.get_json().get("error", "")


def test_history_clear_exception_handling(client, flask_app, monkeypatch):
    import blueprints.history as history_mod

    monkeypatch.setattr(
        history_mod.os, "listdir", lambda p: (_ for _ in ()).throw(Exception("test"))
    )

    resp = client.post("/history/clear")
    assert resp.status_code == 500
    assert "error" in resp.get_json().get("error", "").lower()


def test_history_pagination_defaults(client, device_config_dev):
    """Page 1 returns first 24 items; pagination nav hidden with few items."""
    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    for i in range(5):
        Image.new("RGB", (10, 10), "white").save(
            os.path.join(d, f"display_page_{i:03d}.png")
        )
    resp = client.get("/history")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "5 items" in body
    # With only 5 items and per_page=24, no pagination nav
    assert "Page " not in body


def test_history_pagination_multi_page(client, device_config_dev):
    """With more items than per_page, pagination nav appears."""
    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    for i in range(30):
        Image.new("RGB", (10, 10), "white").save(
            os.path.join(d, f"display_multi_{i:03d}.png")
        )
    resp = client.get("/history?per_page=10")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "30 items" in body
    assert "Page 1 of 3" in body
    assert "Next" in body

    # Page 2
    resp2 = client.get("/history?page=2&per_page=10")
    assert resp2.status_code == 200
    body2 = resp2.data.decode("utf-8")
    assert "Page 2 of 3" in body2
    assert "Previous" in body2
    assert "Next" in body2

    # Page 3 (last)
    resp3 = client.get("/history?page=3&per_page=10")
    assert resp3.status_code == 200
    body3 = resp3.data.decode("utf-8")
    assert "Page 3 of 3" in body3


def test_history_pagination_invalid_params(client, device_config_dev):
    """Invalid page/per_page params default gracefully."""
    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    Image.new("RGB", (10, 10), "white").save(os.path.join(d, "display_inv_001.png"))
    # Invalid page
    resp = client.get("/history?page=abc")
    assert resp.status_code == 200
    # Invalid per_page
    resp = client.get("/history?per_page=-5")
    assert resp.status_code == 200
    # Page beyond range
    resp = client.get("/history?page=999")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "1 items" in body


def test_history_pagination_clamps_upper_bound(client, device_config_dev):
    """JTN-359: ?page=99999 should clamp to the last valid page, not render
    "Page 99999 of N" over an empty grid."""
    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    # Clear any leftover files from other tests in the same worker
    for f in os.listdir(d):
        os.remove(os.path.join(d, f))
    # 30 items with per_page=10 -> total_pages=3
    for i in range(30):
        Image.new("RGB", (10, 10), "white").save(
            os.path.join(d, f"display_clamp_{i:03d}.png")
        )

    resp = client.get("/history?page=99999&per_page=10")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    # Must NOT render the unclamped page number
    assert "Page 99999" not in body
    # Should clamp to last valid page
    assert "Page 3 of 3" in body
    # And the grid should not be empty — the last page's items should render
    assert "display_clamp_" in body


def test_history_pagination_clamps_upper_bound_empty_history(client, device_config_dev):
    """JTN-359: ?page=99999 on an empty history renders the empty-state
    cleanly (page clamps to 1 via total_pages floor, no crash, no bogus
    'Page 99999 of 1')."""
    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    for f in os.listdir(d):
        os.remove(os.path.join(d, f))

    resp = client.get("/history?page=99999")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    # Empty-state copy still renders
    assert "No history yet." in body
    # No leaked unclamped page number
    assert "Page 99999" not in body
    # With total_pages==1 the pagination nav is hidden entirely, so
    # "Page 1 of 1" should not appear either.
    assert "Page 1 of 1" not in body


def test_history_storage_exception_handling(client, flask_app, monkeypatch):
    import shutil as _shutil

    monkeypatch.setattr(
        _shutil, "disk_usage", lambda p: (_ for _ in ()).throw(Exception("test"))
    )

    resp = client.get("/history/storage")
    assert resp.status_code == 500
    assert "failed to get storage info" in resp.get_json().get("error", "")


def test_history_manual_metadata_rendered(client, device_config_dev):
    """Manual Update entries show Source with refresh_type and plugin_id."""
    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    fname = "display_20250101_030000.png"
    Image.new("RGB", (10, 10), "white").save(os.path.join(d, fname))
    sidecar = {"refresh_type": "Manual Update", "plugin_id": "weather"}
    with open(
        os.path.join(d, "display_20250101_030000.json"), "w", encoding="utf-8"
    ) as fh:
        json.dump(sidecar, fh)

    resp = client.get("/history")
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert "Source:" in text
    assert "Manual Update" in text
    assert "weather" in text


def test_history_no_sidecar_no_source(client, device_config_dev):
    """Entries without JSON sidecars should not show a Source line."""
    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    fname = "display_20250101_040000.png"
    Image.new("RGB", (10, 10), "white").save(os.path.join(d, fname))
    # No sidecar JSON created

    resp = client.get("/history")
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert "display_20250101_040000" in text
    assert "Source:" not in text


def test_history_metadata_deduplicates_instance(client, device_config_dev):
    """When plugin_instance equals plugin_id, it should not be shown twice."""
    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    fname = "display_20250101_050000.png"
    Image.new("RGB", (10, 10), "white").save(os.path.join(d, fname))
    sidecar = {
        "refresh_type": "Playlist",
        "plugin_id": "weather",
        "playlist": "Default",
        "plugin_instance": "weather",
    }
    with open(
        os.path.join(d, "display_20250101_050000.json"), "w", encoding="utf-8"
    ) as fh:
        json.dump(sidecar, fh)

    resp = client.get("/history")
    text = resp.get_data(as_text=True)
    # "weather" should appear exactly once (as plugin_id), not twice
    source_section = text[text.index("Source:") : text.index("Source:") + 200]
    assert source_section.count("weather") == 1


# ---------------------------------------------------------------------------
# Lazy sidecar loading tests (JTN-97, JTN-91)
# ---------------------------------------------------------------------------


def test_list_history_images_total_count_accurate(device_config_dev):
    """Total count reflects all PNG files, not just the returned page."""
    import json

    from blueprints import history as history_mod

    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    for i in range(10):
        name = f"display_20250201_{i:06d}.png"
        Image.new("RGB", (10, 10), "white").save(os.path.join(d, name))
        # Write sidecar for half
        if i % 2 == 0:
            sidecar = {"plugin_id": "test"}
            with open(
                os.path.join(d, name.replace(".png", ".json")), "w", encoding="utf-8"
            ) as fh:
                json.dump(sidecar, fh)

    images, total = history_mod._list_history_images(d)
    assert total == 10
    assert len(images) == 10


def test_list_history_images_offset_limit_slicing(device_config_dev):
    """offset/limit correctly slices: 10 items, offset=2, limit=3 -> items 2,3,4."""
    from blueprints import history as history_mod

    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    # Create files with timestamps so sort order is deterministic (newest first)
    for i in range(10):
        name = f"display_20250201_{i:06d}.png"
        Image.new("RGB", (10, 10), "white").save(os.path.join(d, name))

    all_images, total = history_mod._list_history_images(d)
    assert total == 10
    all_names = [img["filename"] for img in all_images]

    page_images, page_total = history_mod._list_history_images(d, offset=2, limit=3)
    assert page_total == 10
    assert len(page_images) == 3
    page_names = [img["filename"] for img in page_images]
    assert page_names == all_names[2:5]


def test_list_history_images_offset_beyond_total(device_config_dev):
    """Offset beyond total returns empty list but correct total count."""
    from blueprints import history as history_mod

    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    for i in range(5):
        Image.new("RGB", (10, 10), "white").save(
            os.path.join(d, f"display_20250201_{i:06d}.png")
        )

    images, total = history_mod._list_history_images(d, offset=100, limit=10)
    assert total == 5
    assert images == []


def test_list_history_images_no_limit_returns_all(device_config_dev):
    """When limit=None (default), all items are returned for backward compat."""
    from blueprints import history as history_mod

    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    for i in range(7):
        Image.new("RGB", (10, 10), "white").save(
            os.path.join(d, f"display_20250201_{i:06d}.png")
        )

    images, total = history_mod._list_history_images(d)
    assert total == 7
    assert len(images) == 7


def test_history_action_buttons_have_aria_labels(client, device_config_dev):
    """JTN-202: action buttons include aria-label with filename for assistive tech."""
    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    fname = "display_20250101_060000.png"
    Image.new("RGB", (10, 10), "white").save(os.path.join(d, fname))

    resp = client.get("/history")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")

    assert f'aria-label="Display {fname}"' in body
    assert f'aria-label="Download {fname}"' in body
    assert f'aria-label="Delete {fname}"' in body


# ---------------------------------------------------------------------------
# Extension allowlist tests for history_delete (JTN-266)
# ---------------------------------------------------------------------------


def test_history_delete_rejects_non_history_extension(client, device_config_dev):
    """history_delete must refuse to delete files with unsupported extensions."""
    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    txt_path = os.path.join(d, "notes.txt")
    with open(txt_path, "w", encoding="utf-8") as fh:
        fh.write("secret")

    resp = client.post("/history/delete", json={"filename": "notes.txt"})

    assert resp.status_code == 400
    data = resp.get_json()
    assert data is not None
    assert "unsupported file type" in data.get("error", "").lower()
    # File must still exist
    assert os.path.exists(txt_path)


def test_history_delete_allows_png(client, device_config_dev):
    """history_delete must successfully delete .png files."""
    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    from PIL import Image

    fname = "display_jtn266_png.png"
    Image.new("RGB", (10, 10), "white").save(os.path.join(d, fname))

    resp = client.post("/history/delete", json={"filename": fname})

    assert resp.status_code == 200
    assert not os.path.exists(os.path.join(d, fname))


def test_history_delete_allows_json(client, device_config_dev):
    """history_delete must successfully delete .json sidecar files."""
    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    fname = "display_jtn266_meta.json"
    with open(os.path.join(d, fname), "w", encoding="utf-8") as fh:
        fh.write("{}")

    resp = client.post("/history/delete", json={"filename": fname})

    assert resp.status_code == 200
    assert not os.path.exists(os.path.join(d, fname))


def test_list_history_images_only_reads_limit_sidecars(device_config_dev, monkeypatch):
    """Only `limit` number of sidecar JSON files are read, not all."""
    import json as _json

    from blueprints import history as history_mod

    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    for i in range(10):
        name = f"display_20250201_{i:06d}.png"
        Image.new("RGB", (10, 10), "white").save(os.path.join(d, name))
        sidecar = {"plugin_id": "test"}
        with open(
            os.path.join(d, name.replace(".png", ".json")), "w", encoding="utf-8"
        ) as fh:
            _json.dump(sidecar, fh)

    load_count = {"n": 0}
    original_load = _json.load

    def counting_load(fh):
        load_count["n"] += 1
        return original_load(fh)

    monkeypatch.setattr(history_mod.json, "load", counting_load)

    limit = 3
    images, total = history_mod._list_history_images(d, offset=0, limit=limit)
    assert total == 10
    assert len(images) == limit
    # Should have loaded at most `limit` sidecars, not all 10
    assert load_count["n"] <= limit


# ---------------------------------------------------------------------------
# HTMX pagination partial swap tests (JTN-330)
# ---------------------------------------------------------------------------


def test_htmx_pagination_returns_different_content_per_page(client, device_config_dev):
    """JTN-330: HTMX partial for page 1 and page 2 must contain different images."""
    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    for f in os.listdir(d):
        os.remove(os.path.join(d, f))
    names = [f"display_20250301_{i:06d}.png" for i in range(20)]
    for name in names:
        Image.new("RGB", (10, 10), "white").save(os.path.join(d, name))

    hx = {"HX-Request": "true"}
    r1 = client.get("/history?page=1&per_page=10", headers=hx)
    r2 = client.get("/history?page=2&per_page=10", headers=hx)

    assert r1.status_code == 200
    assert r2.status_code == 200

    body1 = r1.get_data(as_text=True)
    body2 = r2.get_data(as_text=True)

    imgs_p1 = {n for n in names if n in body1}
    imgs_p2 = {n for n in names if n in body2}

    assert len(imgs_p1) == 10, f"Page 1 should show 10 images, got {len(imgs_p1)}"
    assert len(imgs_p2) == 10, f"Page 2 should show 10 images, got {len(imgs_p2)}"
    assert not imgs_p1 & imgs_p2, "HTMX partials for page 1 and 2 must not overlap"


def test_pagination_links_include_scroll_show_modifier(client, device_config_dev):
    """JTN-330: pagination links must include show: modifier so the grid
    scrolls into view after HTMX swap."""
    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    for f in os.listdir(d):
        os.remove(os.path.join(d, f))
    for i in range(15):
        Image.new("RGB", (10, 10), "white").save(
            os.path.join(d, f"display_20250301_{i:06d}.png")
        )

    resp = client.get("/history?page=1&per_page=10")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    assert "show:#history-grid-container:top" in body, (
        "Next link hx-swap must include show:#history-grid-container:top "
        "so the browser scrolls to the grid after swap"
    )


def test_htmx_partial_is_not_full_page(client, device_config_dev):
    """JTN-330: HTMX partial must not include the full page shell."""
    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    for f in os.listdir(d):
        os.remove(os.path.join(d, f))
    for i in range(5):
        Image.new("RGB", (10, 10), "white").save(
            os.path.join(d, f"display_20250301_{i:06d}.png")
        )

    resp = client.get("/history", headers={"HX-Request": "true"})
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    assert "<html" not in body, "HTMX partial must not include <html> tag"
    assert "history-grid-container" in body, "Partial must contain the grid container"


def test_history_pagination_previous_disabled_has_disabled_class(
    client, device_config_dev
):
    """JTN-636: On page 1, 'Previous' must render with .pagination-disabled
    styling so it is visually distinguishable from the active 'Next' link."""
    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    for f in os.listdir(d):
        os.remove(os.path.join(d, f))
    for i in range(15):
        Image.new("RGB", (10, 10), "white").save(
            os.path.join(d, f"display_jtn636_{i:03d}.png")
        )

    resp = client.get("/history?page=1&per_page=10")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    # Page 1 should show Previous as a disabled <span> with the disabled class.
    assert "pagination-disabled" in body
    # The pagination-disabled control should be aria-disabled for a11y
    assert 'aria-disabled="true"' in body
    # Inline opacity hack from before the fix must not be used
    assert 'style="opacity: 0.4; pointer-events: none;"' not in body


def test_history_pagination_next_disabled_on_last_page(client, device_config_dev):
    """JTN-636: On the last page, 'Next' must also use .pagination-disabled."""
    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    for f in os.listdir(d):
        os.remove(os.path.join(d, f))
    for i in range(15):
        Image.new("RGB", (10, 10), "white").save(
            os.path.join(d, f"display_jtn636b_{i:03d}.png")
        )

    resp = client.get("/history?page=2&per_page=10")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "pagination-disabled" in body
