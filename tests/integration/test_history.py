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


def test_history_redisplay_succeeds(client, device_config_dev, monkeypatch):
    # Create one image
    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    filename = "display_20250101_000200.png"
    path = os.path.join(d, filename)
    Image.new("RGB", (10, 10), "white").save(path)

    # Spy on display_preprocessed_image
    call_count = [0]
    last_path = [""]
    display_manager = client.application.config['DISPLAY_MANAGER']
    original = display_manager.display_preprocessed_image

    def _spy(p):
        call_count[0] += 1
        last_path[0] = str(p)
        return original(p)

    monkeypatch.setattr(display_manager, "display_preprocessed_image", _spy, raising=True)

    resp = client.post("/history/redisplay", json={"filename": filename})
    assert resp.status_code == 200
    assert call_count[0] == 1
    assert last_path[0].endswith(filename)


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


def test_history_storage_endpoint_values(client, monkeypatch):
    # Monkeypatch statvfs to return known numbers for precise assertions
    class FakeStat:
        f_frsize = 4096
        f_bavail = 250_000
        f_blocks = 1_000_000

    import os as _os
    monkeypatch.setattr(_os, "statvfs", lambda p: FakeStat())

    resp = client.get("/history/storage")
    assert resp.status_code == 200
    data = resp.get_json()
    assert set(["free_gb", "total_gb", "used_gb", "pct_free"]).issubset(data.keys())
    # With values above, totals should be deterministic with 2-decimal rounding
    assert data["total_gb"] == 3.81
    assert data["free_gb"] == 0.95
    assert data["used_gb"] == 2.86
    assert data["pct_free"] == 25.0


def test_history_clear_then_storage_endpoint_ok(client, device_config_dev):
    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    from PIL import Image
    for i in range(3):
        Image.new("RGB", (10, 10), "white").save(os.path.join(d, f"display_20250101_00060{i}.png"))

    resp = client.post("/history/clear")
    assert resp.status_code == 200
    assert len([f for f in os.listdir(d) if f.endswith('.png')]) == 0

    resp2 = client.get("/history/storage")
    assert resp2.status_code == 200
    data2 = resp2.get_json()
    assert data2.get("pct_free") is None or (0.0 <= float(data2.get("pct_free")) <= 100.0)


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
    time.sleep(0.01)
    Image.new("RGB", (20, 20), "white").save(b)

    # Touch sizes for clear difference
    os.truncate(a, 100)
    os.truncate(b, 2048)

    resp = client.get("/history")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")

    # Newest first - b should appear before a in the HTML
    idx_b = body.find("b.png")
    idx_a = body.find("a.png")
    assert idx_b != -1 and idx_a != -1 and idx_b < idx_a

    # Size strings should include units like B or KB
    assert "100 B" in body or "0.1 KB" in body or "KB" in body

