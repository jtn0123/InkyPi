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

