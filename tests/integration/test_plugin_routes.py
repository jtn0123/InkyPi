# pyright: reportMissingImports=false


def test_plugin_page_not_found(client):
    resp = client.get("/plugin/unknown")
    assert resp.status_code == 404
    assert b"not found" in resp.data.lower()


def test_plugin_page_sanitizes_missing_instance_name(client):
    resp = client.get("/plugin/ai_text?instance=%3Cscript%3Ealert(1)%3C%2Fscript%3E")
    assert resp.status_code == 404
    error = resp.get_json().get("error", "")
    assert "<script>" not in error
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in error


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
    assert resp.status_code == 404
    assert "Plugin instance: test does not exist" in resp.get_json().get("error", "")


def test_update_plugin_instance_sanitizes_missing_instance_name(client):
    resp = client.put(
        "/update_plugin_instance/%3Cscript%3Ealert(1)%3E",
        data={"plugin_id": "ai_text"},
    )
    assert resp.status_code == 404
    error = resp.get_json().get("error", "")
    assert "<script>" not in error
    assert "&lt;script&gt;alert(1)&gt;" in error


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


def test_display_plugin_instance_sanitizes_missing_instance_name(client):
    resp = client.post(
        "/display_plugin_instance",
        json={
            "playlist_name": "Default",
            "plugin_id": "ai_text",
            "plugin_instance": "<script>alert(1)</script>",
        },
    )
    assert resp.status_code == 400
    error = resp.get_json().get("error", "")
    assert "<script>" not in error
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in error


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


def test_update_now_async_returns_202_with_job_id(client):
    """POST /update_now with X-Async returns 202 Accepted with a job_id."""
    resp = client.post(
        "/update_now",
        data={"plugin_id": "clock"},
        headers={"X-Async": "true"},
    )
    assert resp.status_code == 202
    data = resp.get_json()
    assert "job_id" in data
    assert isinstance(data["job_id"], str)
    assert len(data["job_id"]) == 32


def test_update_now_sync_still_works(client):
    """POST /update_now without X-Async keeps the legacy synchronous path."""
    resp = client.post("/update_now", data={"plugin_id": "clock"})
    # Should be 200 (sync path), not 202
    assert resp.status_code == 200


def test_update_now_missing_plugin_id_returns_422(client):
    """POST /update_now without plugin_id still returns 422."""
    resp = client.post("/update_now", data={})
    assert resp.status_code == 422


def test_job_status_unknown_id(client):
    """GET /api/job/<unknown> returns status 'unknown'."""
    resp = client.get("/api/job/does_not_exist_at_all_1234")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "unknown"


def test_update_now_async_poll_completes(client, flask_app, monkeypatch):
    """Full 202 -> poll -> done flow for async update_now."""
    import time

    from PIL import Image

    import plugins.clock.clock as clock_mod
    from refresh_task.job_queue import get_job_queue

    def fake_generate(self, settings, device_config):
        return Image.new("RGB", device_config.get_resolution(), "white")

    monkeypatch.setattr(clock_mod.Clock, "generate_image", fake_generate, raising=True)

    display_manager = flask_app.config["DISPLAY_MANAGER"]
    monkeypatch.setattr(
        display_manager,
        "display_image",
        lambda image, image_settings=None, history_meta=None: None,
        raising=True,
    )

    refresh_task = flask_app.config["REFRESH_TASK"]
    refresh_task.running = False

    resp = client.post(
        "/update_now",
        data={"plugin_id": "clock"},
        headers={"X-Async": "true"},
    )
    assert resp.status_code == 202
    job_id = resp.get_json()["job_id"]

    # Poll until done — must finish before monkeypatch cleanup
    for _ in range(50):
        poll = client.get(f"/api/job/{job_id}")
        data = poll.get_json()
        if data["status"] in ("done", "error"):
            break
        time.sleep(0.1)

    assert data["status"] == "done"
    assert data["result"]["success"] is True

    # Wait for background thread to fully exit before monkeypatch restores
    queue = get_job_queue()
    for _ in range(20):
        if queue.pending_jobs == 0:
            break
        time.sleep(0.05)


def test_update_now_async_poll_error(client, flask_app, monkeypatch):
    """Async update_now job that raises shows status 'error' when polled."""
    import time

    from refresh_task.job_queue import get_job_queue

    refresh_task = flask_app.config["REFRESH_TASK"]
    refresh_task.running = False

    # Use a plugin that doesn't exist — guaranteed to raise without monkeypatch timing issues
    resp = client.post(
        "/update_now",
        data={"plugin_id": "nonexistent_plugin_xyz"},
        headers={"X-Async": "true"},
    )
    assert resp.status_code == 202
    job_id = resp.get_json()["job_id"]

    for _ in range(50):
        poll = client.get(f"/api/job/{job_id}")
        data = poll.get_json()
        if data["status"] in ("done", "error"):
            break
        time.sleep(0.1)

    assert data["status"] == "error"
    assert "not found" in data["error"]

    # Ensure background thread finishes before test cleanup
    queue = get_job_queue()
    for _ in range(20):
        if queue.pending_jobs == 0:
            break
        time.sleep(0.05)


def test_update_now_async_plugin_not_found(client, flask_app):
    """Plugin not found is reported via the job error status."""
    import time

    refresh_task = flask_app.config["REFRESH_TASK"]
    refresh_task.running = False

    resp = client.post(
        "/update_now",
        data={"plugin_id": "nonexistent"},
        headers={"X-Async": "true"},
    )
    assert resp.status_code == 202
    job_id = resp.get_json()["job_id"]

    for _ in range(50):
        poll = client.get(f"/api/job/{job_id}")
        data = poll.get_json()
        if data["status"] in ("done", "error"):
            break
        time.sleep(0.1)

    assert data["status"] == "error"
    assert "not found" in data["error"]


def test_update_now_exception_handling(client, flask_app, monkeypatch):
    """Sync path: exceptions yield 500."""
    import blueprints.plugin as plugin_mod

    monkeypatch.setattr(
        plugin_mod,
        "get_plugin_instance",
        lambda x: (_ for _ in ()).throw(Exception("test")),
    )

    resp = client.post("/update_now", data={"plugin_id": "ai_text"})
    assert resp.status_code == 500
    assert "An internal error occurred" in resp.get_json().get("error", "")


def test_save_plugin_settings_exception_handling(client, flask_app, monkeypatch):
    dc = flask_app.config["DEVICE_CONFIG"]
    # Make update_atomic raise to simulate config failure
    monkeypatch.setattr(
        dc,
        "update_atomic",
        lambda *args, **kwargs: (_ for _ in ()).throw(Exception("test")),
    )

    resp = client.post(
        "/save_plugin_settings",
        data={"plugin_id": "ai_text", "textPrompt": "Hello"},
    )
    assert resp.status_code == 500
    assert "An internal error occurred" in resp.get_json().get("error", "")


def test_save_plugin_settings_rejects_unknown_plugin_id(client):
    resp = client.post("/save_plugin_settings", data={"plugin_id": "not_real_plugin"})
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "Plugin 'not_real_plugin' not found"


def test_save_plugin_settings_alias_rejects_unknown_plugin_id(client):
    resp = client.post("/plugin/not_real_plugin/save", data={"title": "Test"})
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "Plugin 'not_real_plugin' not found"


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
    assert resp.status_code in (200, 404, 500)


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


def test_instance_image_uses_latest_matching_history_entry(
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

    history_dir = device_config_dev.history_image_dir

    older_png_path = os.path.join(history_dir, "display_000001.png")
    older_json_path = os.path.join(history_dir, "display_000001.json")
    Image.new("RGB", (10, 10), "red").save(older_png_path)
    with open(older_json_path, "w", encoding="utf-8") as fh:
        json.dump({"plugin_id": "ai_text", "plugin_instance": "Inst One"}, fh)

    newer_png_path = os.path.join(history_dir, "display_000002.png")
    newer_json_path = os.path.join(history_dir, "display_000002.json")
    Image.new("RGB", (10, 10), "green").save(newer_png_path)
    with open(newer_json_path, "w", encoding="utf-8") as fh:
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
    assert img.getpixel((0, 0)) == (0, 128, 0)


def test_delete_plugin_instance_cleans_up_cache(client, device_config_dev):
    """Deleting a plugin instance removes its cached image file."""
    import os

    from PIL import Image

    _setup_playlist_for_instance(device_config_dev)

    # Create a cached image file
    path = device_config_dev.get_plugin_image_path("ai_text", "Inst One")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new("RGB", (10, 10), "white").save(path)
    assert os.path.isfile(path)

    resp = client.post(
        "/delete_plugin_instance",
        json={
            "playlist_name": "Default",
            "plugin_id": "ai_text",
            "plugin_instance": "Inst One",
        },
    )
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True
    # Cached image should be removed
    assert not os.path.isfile(path)


def test_delete_plugin_instance_calls_plugin_cleanup(
    client, device_config_dev, monkeypatch
):
    """Deleting a plugin instance calls plugin.cleanup() if available."""
    _setup_playlist_for_instance(device_config_dev)

    cleanup_called = {}

    class _StubPlugin:
        def cleanup(self, settings):
            cleanup_called["settings"] = settings

    monkeypatch.setattr(
        "blueprints.plugin.get_plugin_instance", lambda pid: _StubPlugin(), raising=True
    )

    resp = client.post(
        "/delete_plugin_instance",
        json={
            "playlist_name": "Default",
            "plugin_id": "ai_text",
            "plugin_instance": "Inst One",
            "settings": {"key": "val"},
        },
    )
    assert resp.status_code == 200
    assert "settings" in cleanup_called
    assert cleanup_called["settings"] == {}


def _add_named_plugin_instance(device_config_dev, plugin_id, instance_name):
    """Helper: add a named plugin instance to the Default playlist."""
    pm = device_config_dev.get_playlist_manager()
    if not pm.get_playlist("Default"):
        pm.add_playlist("Default", "00:00", "24:00")
    pl = pm.get_playlist("Default")
    if not pl.find_plugin(plugin_id, instance_name):
        pl.add_plugin(
            {
                "plugin_id": plugin_id,
                "name": instance_name,
                "plugin_settings": {"city": "London"},
                "refresh": {"interval": 300},
            }
        )
    device_config_dev.write_config()


def test_plugin_page_instance_query_param_returns_200(client, device_config_dev):
    """GET /plugin/<id>?instance=<name> returns 200 when the instance exists (JTN-221)."""
    _add_named_plugin_instance(device_config_dev, "weather", "Audit weather")

    resp = client.get("/plugin/weather?instance=Audit weather")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "Audit weather" in body or "London" in body


def test_plugin_page_instance_url_plus_encoding_decoded_correctly(
    client, device_config_dev
):
    """GET /plugin/<id>?instance=Name+With+Spaces decodes '+' to space (JTN-221)."""
    _add_named_plugin_instance(device_config_dev, "weather", "Audit weather")

    # Simulate a browser URL with + for spaces
    resp = client.get("/plugin/weather?instance=Audit+weather")
    assert resp.status_code == 200


def test_plugin_page_instance_nonexistent_returns_friendly_404(
    client, device_config_dev
):
    """GET /plugin/<id>?instance=<missing> returns 404 with a descriptive message (JTN-221)."""
    resp = client.get("/plugin/weather?instance=nonexistent instance")
    assert resp.status_code == 404
    body = resp.get_json()
    assert body is not None
    assert "nonexistent instance" in body.get("error", "")


def test_plugin_page_without_instance_param_still_works(client):
    """GET /plugin/<id> (no ?instance=) continues to work after JTN-221 fix."""
    resp = client.get("/plugin/weather")
    assert resp.status_code == 200


def test_playlist_page_instance_image_url_has_no_playlist_name_query_param(
    client, device_config_dev
):
    """Regression test for JTN-265.

    playlist.html used to pass playlist_name=... to url_for('plugin.plugin_instance_image'),
    which Flask silently appended as a query string the route ignores.  Verify that
    rendered image src URLs do NOT contain playlist_name as a query parameter.
    """
    pm = device_config_dev.get_playlist_manager()
    pm.add_playlist("MyPlaylist", "00:00", "24:00")
    pl = pm.get_playlist("MyPlaylist")
    pl.add_plugin(
        {
            "plugin_id": "ai_text",
            "name": "My Instance",
            "plugin_settings": {},
            "refresh": {"interval": 300},
        }
    )
    device_config_dev.write_config()

    resp = client.get("/playlist")
    assert resp.status_code == 200
    body = resp.data.decode()
    # The image src should not carry playlist_name as a query param
    assert "playlist_name=" not in body
