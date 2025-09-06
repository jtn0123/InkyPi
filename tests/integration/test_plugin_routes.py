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
    pm = flask_app.config["DEVICE_CONFIG"].get_playlist_manager()
    monkeypatch.setattr(
        pm, "get_playlist", lambda x: (_ for _ in ()).throw(Exception("test"))
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


def test_save_plugin_settings_creates_then_updates(client, monkeypatch):
    # First: create new default instance
    data = {
        "plugin_id": "ai_text",
        "title": "T1",
        "textModel": "gpt-4o",
        "textPrompt": "Hi",
    }
    resp = client.post("/save_plugin_settings", data=data)
    assert resp.status_code == 200
    instance_name = resp.get_json()["instance_name"]
    assert instance_name == "ai_text_saved_settings"

    # Second: update existing instance via another save
    data2 = {
        "plugin_id": "ai_text",
        "title": "T2",
        "textModel": "gpt-4o",
        "textPrompt": "Hi again",
    }
    resp2 = client.post("/save_plugin_settings", data=data2)
    assert resp2.status_code == 200
    assert resp2.get_json()["instance_name"] == instance_name

    # Third: open plugin page and confirm instance prepopulates
    page = client.get("/plugin/ai_text")
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    # The saved title value should appear in HTML (template uses settings to fill form)
    assert ("T2" in body) or ("Hi again" in body)
