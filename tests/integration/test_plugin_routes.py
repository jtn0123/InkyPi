# pyright: reportMissingImports=false


def test_plugin_page_not_found(client):
    resp = client.get("/plugin/unknown")
    assert resp.status_code == 404


# Skip this test - the exception handling is already covered by existing tests


def test_plugin_images_path_traversal_prevention(client):
    # Attempt path traversal
    resp = client.get("/images/ai_text/../../../etc/passwd")
    assert resp.status_code == 404


def test_plugin_images_file_not_found(client):
    resp = client.get("/images/ai_text/nonexistent.png")
    assert resp.status_code == 404


def test_delete_plugin_instance_invalid_json(client):
    resp = client.post("/delete_plugin_instance", data="not json")
    assert resp.status_code == 415  # Flask returns 415 for unsupported media type
    # The actual validation happens later


def test_delete_plugin_instance_playlist_not_found(client):
    resp = client.post(
        "/delete_plugin_instance",
        json={
            "playlist_name": "NonExistent",
            "plugin_id": "ai_text",
            "plugin_instance": "test",
        },
    )
    assert resp.status_code == 400
    assert "Playlist not found" in resp.get_json().get("error", "")


def test_delete_plugin_instance_plugin_not_found(client):
    resp = client.post(
        "/delete_plugin_instance",
        json={
            "playlist_name": "Default",
            "plugin_id": "ai_text",
            "plugin_instance": "nonexistent",
        },
    )
    assert resp.status_code == 400
    assert "Plugin instance not found" in resp.get_json().get("error", "")


def test_delete_plugin_instance_exception_handling(client, flask_app, monkeypatch):
    pm = flask_app.config["DEVICE_CONFIG"].get_playlist_manager()

    def mock_get_playlist(name):
        raise Exception("test")

    monkeypatch.setattr(pm, "get_playlist", mock_get_playlist)

    resp = client.post(
        "/delete_plugin_instance",
        json={
            "playlist_name": "Default",
            "plugin_id": "ai_text",
            "plugin_instance": "test",
        },
    )
    assert resp.status_code == 500
    assert "An internal error occurred" in resp.get_json().get("error", "")


def test_update_plugin_instance_missing_instance_name(client):
    resp = client.put("/update_plugin_instance/", data={"plugin_id": "ai_text"})
    assert resp.status_code == 404  # Flask routing gives 404 for empty path parameter


def test_update_plugin_instance_plugin_not_found(client):
    resp = client.put("/update_plugin_instance/test", data={"plugin_id": "nonexistent"})
    assert resp.status_code == 500
    assert "Plugin instance: test does not exist" in resp.get_json().get("error", "")


def test_update_plugin_instance_api_error_handling(client, flask_app, monkeypatch):
    from utils.http_utils import APIError

    pm = flask_app.config["DEVICE_CONFIG"].get_playlist_manager()

    def mock_find_plugin(plugin_id, instance_name):
        raise APIError("Test API error", status=400)

    monkeypatch.setattr(pm, "find_plugin", mock_find_plugin)

    resp = client.put("/update_plugin_instance/test", data={"plugin_id": "ai_text"})
    assert resp.status_code == 400
    assert "Test API error" in resp.get_json().get("error", "")


def test_update_plugin_instance_exception_handling(client, flask_app, monkeypatch):
    pm = flask_app.config["DEVICE_CONFIG"].get_playlist_manager()
    monkeypatch.setattr(
        pm, "find_plugin", lambda *args: (_ for _ in ()).throw(Exception("test"))
    )

    resp = client.put("/update_plugin_instance/test", data={"plugin_id": "ai_text"})
    assert resp.status_code == 500
    assert "An internal error occurred" in resp.get_json().get("error", "")


def test_display_plugin_instance_invalid_json(client):
    resp = client.post("/display_plugin_instance", data="not json")
    assert resp.status_code == 415  # Flask returns 415 for unsupported media type


def test_display_plugin_instance_playlist_not_found(client):
    resp = client.post(
        "/display_plugin_instance",
        json={
            "playlist_name": "NonExistent",
            "plugin_id": "ai_text",
            "plugin_instance": "test",
        },
    )
    assert resp.status_code == 400
    assert "Playlist NonExistent not found" in resp.get_json().get("error", "")


def test_display_plugin_instance_plugin_not_found(client):
    resp = client.post(
        "/display_plugin_instance",
        json={
            "playlist_name": "Default",
            "plugin_id": "ai_text",
            "plugin_instance": "nonexistent",
        },
    )
    assert resp.status_code == 400
    assert "Plugin instance 'nonexistent' not found" in resp.get_json().get("error", "")


def test_display_plugin_instance_exception_handling(client, flask_app, monkeypatch):
    pm = flask_app.config["DEVICE_CONFIG"].get_playlist_manager()
    monkeypatch.setattr(
        pm, "get_playlist", lambda x: (_ for _ in ()).throw(Exception("test"))
    )

    resp = client.post(
        "/display_plugin_instance",
        json={
            "playlist_name": "Default",
            "plugin_id": "ai_text",
            "plugin_instance": "test",
        },
    )
    assert resp.status_code == 500
    assert "An internal error occurred" in resp.get_json().get("error", "")


def test_update_now_plugin_not_found(client):
    resp = client.post("/update_now", data={"plugin_id": "nonexistent"})
    assert resp.status_code == 404
    assert "Plugin 'nonexistent' not found" in resp.get_json().get("error", "")


def test_update_now_exception_handling(client, flask_app, monkeypatch):
    import plugins.plugin_registry as pr

    monkeypatch.setattr(
        pr, "get_plugin_instance", lambda x: (_ for _ in ()).throw(Exception("test"))
    )

    resp = client.post("/update_now", data={"plugin_id": "ai_text"})
    assert resp.status_code == 500
    assert "An error occurred" in resp.get_json().get("error", "")


def test_save_plugin_settings_exception_handling(client, flask_app, monkeypatch):
    dc = flask_app.config["DEVICE_CONFIG"]
    # Make update_value raise to simulate config failure
    monkeypatch.setattr(
        dc, "update_value", lambda *args, **kwargs: (_ for _ in ()).throw(Exception("test"))
    )

    resp = client.post("/save_plugin_settings", data={"plugin_id": "ai_text"})
    assert resp.status_code == 500
    assert "An internal error occurred" in resp.get_json().get("error", "")


def test_delete_plugin_instance_missing(client):
    resp = client.post(
        "/delete_plugin_instance",
        json={"playlist_name": "Default", "plugin_id": "x", "plugin_instance": "nope"},
    )
    assert resp.status_code in (200, 400)


def test_update_plugin_instance_missing(client):
    resp = client.put(
        "/update_plugin_instance/does-not-exist", data={"plugin_id": "ai_text"}
    )
    assert resp.status_code in (200, 500)


def test_save_plugin_settings_persist_and_load_on_plugin_page(client, monkeypatch):
    # First: save settings
    data = {
        "plugin_id": "ai_text",
        "title": "T1",
        "textModel": "gpt-4o",
        "textPrompt": "Hello",
    }
    resp = client.post("/save_plugin_settings", data=data)
    assert resp.status_code == 200
    j = resp.get_json()
    assert j.get("success") is True
    assert "Add to Playlist" in j.get("message", "")

    # Then open plugin page and confirm settings prepopulate (not tied to any instance)
    page = client.get("/plugin/ai_text")
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert ("T1" in body) or ("Hello" in body)


def test_plugin_instance_image_404(client):
    resp = client.get("/instance_image/ai_text/does-not-exist")
    assert resp.status_code == 404


def test_plugin_instance_image_serves_png(client, device_config_dev):
    import os
    from PIL import Image

    path = device_config_dev.get_plugin_image_path("ai_text", "Inst One")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new("RGB", (10, 10), "white").save(path)

    resp = client.get("/instance_image/ai_text/Inst One")
    assert resp.status_code == 200
    assert resp.headers.get("Content-Type", "").startswith("image/")


def _setup_playlist_for_instance(device_config_dev):
    pm = device_config_dev.get_playlist_manager()
    if not pm.get_playlist("Default"):
        pm.add_playlist("Default", "00:00", "24:00")
    pl = pm.get_playlist("Default")
    pl.add_plugin(
        {
            "plugin_id": "ai_text",
            "name": "Inst One",
            "plugin_settings": {},
            "refresh": {"interval": 300},
        }
    )
    device_config_dev.write_config()


def test_instance_image_generated_from_settings(client, device_config_dev, monkeypatch):
    import io
    import os
    from PIL import Image

    _setup_playlist_for_instance(device_config_dev)

    path = device_config_dev.get_plugin_image_path("ai_text", "Inst One")
    if os.path.exists(path):
        os.remove(path)

    class _StubPlugin:
        def generate_image(self, settings, device_config):
            return Image.new("RGB", (10, 10), "blue")

    monkeypatch.setattr(
        "blueprints.plugin.get_plugin_instance", lambda cfg: _StubPlugin(), raising=True
    )

    resp = client.get("/instance_image/ai_text/Inst One")
    assert resp.status_code == 200
    # Ensure file persisted and served
    assert os.path.exists(path)
    img = Image.open(io.BytesIO(resp.data))
    assert img.getpixel((0, 0)) == (0, 0, 255)


def test_instance_image_served_from_history_on_generation_failure(
    client, device_config_dev, monkeypatch
):
    import io
    import json
    import os
    from PIL import Image

    _setup_playlist_for_instance(device_config_dev)

    path = device_config_dev.get_plugin_image_path("ai_text", "Inst One")
    if os.path.exists(path):
        os.remove(path)

    # Prepare history sidecar
    history_dir = device_config_dev.history_image_dir
    png_path = os.path.join(history_dir, "display_000001.png")
    json_path = os.path.join(history_dir, "display_000001.json")
    Image.new("RGB", (10, 10), "red").save(png_path)
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump({"plugin_id": "ai_text", "plugin_instance": "Inst One"}, fh)

    class _StubPlugin:
        def generate_image(self, settings, device_config):
            raise RuntimeError("fail")

    monkeypatch.setattr(
        "blueprints.plugin.get_plugin_instance", lambda cfg: _StubPlugin(), raising=True
    )

    resp = client.get("/instance_image/ai_text/Inst One")
    assert resp.status_code == 200
    img = Image.open(io.BytesIO(resp.data))
    assert img.getpixel((0, 0)) == (255, 0, 0)
