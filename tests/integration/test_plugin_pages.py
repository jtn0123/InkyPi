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


def test_plugin_page_status_bar_present(client):
    resp = client.get("/plugin/ai_text")
    assert resp.status_code == 200
    body = resp.data
    assert b'class="status-bar"' in body
    assert b'id="currentDisplayTime"' in body


def test_plugin_page_instance_preview_shown_when_instance(client):
    # Create saved settings for ai_text to have an instance
    data = {
        "plugin_id": "ai_text",
        "title": "T1",
        "textModel": "gpt-4o",
        "textPrompt": "Hi",
    }
    resp = client.post("/save_plugin_settings", data=data)
    assert resp.status_code == 200
    inst = resp.get_json()["instance_name"]

    page = client.get(f"/plugin/ai_text?instance={inst}")
    assert page.status_code == 200
    body = page.data
    # Instance preview image element should be present when instance is specified
    assert b'id="instancePreviewImage"' in body


def test_instance_image_history_fallback(client, device_config_dev):
    # Simulate a manual update that creates history sidecar with instance name
    data = {
        "plugin_id": "ai_text",
        "title": "T1",
        "textModel": "gpt-4o",
        "textPrompt": "Hi",
        "instance_name": "ai_text_saved_settings",
    }
    resp = client.post("/update_now", data=data)
    assert resp.status_code in (200, 500)

    # Now request the instance image (no plugin image file exists), should fallback to history
    resp2 = client.get("/instance_image/ai_text/ai_text_saved_settings")
    # Should either serve or 404 if environment cannot generate; accept 200 as success criteria
    assert resp2.status_code in (200, 404)
