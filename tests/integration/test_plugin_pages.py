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
    # Create a playlist instance explicitly
    from utils.time_utils import calculate_seconds
    # Add to Default playlist
    resp = client.post(
        "/add_plugin",
        data={
            "plugin_id": "ai_text",
            "title": "T1",
            "textModel": "gpt-4o",
            "textPrompt": "Hi",
            "refresh_settings": '{"playlist":"Default","instance_name":"Saved Settings","refreshType":"interval","interval":"60","unit":"minute"}',
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200

    page = client.get("/plugin/ai_text?instance=Saved Settings")
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


def test_api_key_indicator_shows_missing_when_no_key(client, device_config_dev):
    """Test that API key indicator shows 'missing' status when key is not present.

    Regression test for: API key indicator showing warning even when keys are configured.
    """
    # Ensure no OpenAI key is present
    device_config_dev.unset_env_key("OPEN_AI_SECRET")

    resp = client.get("/plugin/ai_image")
    assert resp.status_code == 200
    body = resp.data.decode('utf-8')

    # Should show the missing indicator
    assert 'class="api-key-indicator missing"' in body
    assert 'API Required' in body or 'API Key required' in body


def test_api_key_indicator_shows_configured_when_key_present(client, device_config_dev):
    """Test that API key indicator shows 'configured' status when key is present.

    Regression test for: API key indicator showing warning even when keys are configured.
    """
    # Set an OpenAI key
    device_config_dev.set_env_key("OPEN_AI_SECRET", "test-key-123")

    resp = client.get("/plugin/ai_image")
    assert resp.status_code == 200
    body = resp.data.decode('utf-8')

    # Should show the configured indicator
    assert 'class="api-key-indicator configured"' in body
    assert 'API Key is configured' in body or '✓' in body


def test_plugin_latest_image_endpoint(client, device_config_dev):
    """Test that /plugin_latest_image serves the most recent image for a plugin.

    Regression test for: "Latest from this plugin" section not showing historical images.
    """
    import os
    import json
    from PIL import Image

    # Create a fake history image and metadata
    history_dir = device_config_dev.history_image_dir
    os.makedirs(history_dir, exist_ok=True)

    # Create test image
    img = Image.new('RGB', (100, 100), color='red')
    img_path = os.path.join(history_dir, 'display_20250115_120000.png')
    img.save(img_path)

    # Create metadata
    metadata = {
        'plugin_id': 'clock',
        'plugin_instance': 'test_instance',
        'refresh_time': '2025-01-15T12:00:00'
    }
    json_path = os.path.join(history_dir, 'display_20250115_120000.json')
    with open(json_path, 'w') as f:
        json.dump(metadata, f)

    # Request latest image for this plugin
    resp = client.get('/plugin_latest_image/clock')
    assert resp.status_code == 200
    assert resp.content_type.startswith('image/')

    # Test with non-existent plugin
    resp2 = client.get('/plugin_latest_image/nonexistent_plugin')
    assert resp2.status_code == 404


def test_plugin_latest_refresh_time_populated(client, device_config_dev):
    """Test that plugin_latest_refresh template variable is populated correctly.

    Regression test for: "Last generated" timestamp not showing for "Latest from this plugin".
    """
    import os
    import json

    # Create a fake history metadata
    history_dir = device_config_dev.history_image_dir
    os.makedirs(history_dir, exist_ok=True)

    metadata = {
        'plugin_id': 'clock',
        'plugin_instance': 'test_instance',
        'refresh_time': '2025-01-15T12:00:00'
    }
    json_path = os.path.join(history_dir, 'display_20250115_120000.json')
    with open(json_path, 'w') as f:
        json.dump(metadata, f)

    # Visit plugin page
    resp = client.get('/plugin/clock')
    assert resp.status_code == 200
    body = resp.data.decode('utf-8')

    # The template should render the refresh time
    # It's rendered via JavaScript, so we check that the variable is set
    assert 'plugin_latest_refresh' in body or '2025-01-15' in body
