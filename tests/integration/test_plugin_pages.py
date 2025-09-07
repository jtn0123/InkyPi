# pyright: reportMissingImports=false


def test_plugin_page_ai_text(client):
    resp = client.get("/plugin/ai_text")
    assert resp.status_code == 200
    assert b"AI Text" in resp.data
    # preview image present
    assert b"/preview" in resp.data


def test_plugin_page_ai_image(client):
    resp = client.get("/plugin/ai_image")
    assert resp.status_code == 200
    assert b"AI Image" in resp.data or b"Image Model" in resp.data
    assert b"/preview" in resp.data


def test_plugin_page_apod(client):
    resp = client.get("/plugin/apod")
    assert resp.status_code == 200
    assert b"APOD" in resp.data or b"NASA" in resp.data
    assert b"/preview" in resp.data


def test_preview_size_mode_native_on_plugin(client, device_config_dev):
    device_config_dev.update_value("preview_size_mode", "native", write=True)
    resp = client.get("/plugin/ai_text")
    assert resp.status_code == 200
    assert b'style="width: ' in resp.data and b"height: " in resp.data


def test_preview_size_mode_fit_on_plugin(client, device_config_dev):
    device_config_dev.update_value("preview_size_mode", "fit", write=True)
    resp = client.get("/plugin/ai_text")
    assert resp.status_code == 200
    assert b'id="previewImage" style=' not in resp.data
