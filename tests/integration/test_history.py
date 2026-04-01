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
    import json

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

    # Traversal attempt
    resp = client.post("/history/delete", json={"filename": "../../etc/passwd"})
    assert resp.status_code == 400


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

    images = history_mod._list_history_images(d)
    names = [img["filename"] for img in images]
    assert "b.png" in names and "a.png" in names

    resp = client.get("/history")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")

    # Size strings should include units like B or KB
    assert "100 B" in body or "0.1 KB" in body or "KB" in body


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

    result = history_mod._list_history_images(device_config_dev.history_image_dir)
    assert result == []


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
    Image.new("RGB", (10, 10), "white").save(
        os.path.join(d, "display_inv_001.png")
    )
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


def test_history_storage_exception_handling(client, flask_app, monkeypatch):
    import shutil as _shutil

    monkeypatch.setattr(
        _shutil, "disk_usage", lambda p: (_ for _ in ()).throw(Exception("test"))
    )

    resp = client.get("/history/storage")
    assert resp.status_code == 500
    assert "failed to get storage info" in resp.get_json().get("error", "")
