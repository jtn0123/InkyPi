# pyright: reportMissingImports=false


def test_main_page(client):
    resp = client.get('/')
    assert resp.status_code == 200
    assert b"/preview" in resp.data


def test_preview_size_mode_native_on_home(client, device_config_dev, monkeypatch):
    # native: expect inline width/height styles present
    device_config_dev.update_value("preview_size_mode", "native", write=True)
    resp = client.get('/')
    assert resp.status_code == 200
    assert b"style=\"width: " in resp.data and b"height: " in resp.data


def test_preview_size_mode_fit_on_home(client, device_config_dev, monkeypatch):
    # fit: expect no explicit inline width/height
    device_config_dev.update_value("preview_size_mode", "fit", write=True)
    resp = client.get('/')
    assert resp.status_code == 200
    assert b"style=\"width:" not in resp.data


def test_preview_404_when_no_image(client):
    resp = client.get('/preview')
    assert resp.status_code == 404


def test_preview_serves_current_image_when_exists(client, device_config_dev):
    # Write a dummy current image
    from PIL import Image
    img = Image.new("RGB", (10, 10), "black")
    img.save(device_config_dev.current_image_file)

    resp = client.get('/preview')
    assert resp.status_code == 200
    assert resp.mimetype == 'image/png'


def test_preview_prefers_processed_over_current(client, device_config_dev):
    from PIL import Image
    # Create different colored images to differentiate
    cur = Image.new("RGB", (10, 10), "black")
    cur.save(device_config_dev.current_image_file)
    proc = Image.new("RGB", (10, 10), "white")
    proc.save(device_config_dev.processed_image_file)

    resp = client.get('/preview')
    assert resp.status_code == 200
    assert resp.mimetype == 'image/png'


