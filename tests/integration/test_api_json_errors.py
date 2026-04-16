# pyright: reportMissingImports=false


def test_update_now_surfaces_plugin_error_json(client, monkeypatch):
    # Make plugin raise
    import plugins.ai_text.ai_text as ai_text_mod

    def boom(self, settings, device_config):
        raise RuntimeError("boom")

    monkeypatch.setattr(ai_text_mod.AIText, "generate_image", boom, raising=True)

    resp = client.post(
        "/update_now",
        data={
            "plugin_id": "ai_text",
            "title": "T",
            "textModel": "gpt-4o",
            "textPrompt": "hi",
        },
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert isinstance(data, dict)
    # JTN-326: plugin RuntimeError text must NOT be echoed back
    # (py/stack-trace-exposure).  Response is now a generic message.
    assert "boom" not in data["error"]
    assert data["error"] == "An internal error occurred"
    assert data.get("code") == "plugin_error"


def test_save_plugin_settings_error_json(client, flask_app, monkeypatch):
    # Simulate a config write failure so endpoint returns JSON error
    dc = flask_app.config["DEVICE_CONFIG"]

    def boom_update_atomic(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(dc, "update_atomic", boom_update_atomic, raising=True)

    resp = client.post(
        "/save_plugin_settings",
        data={"plugin_id": "ai_text", "textPrompt": "Hello", "textModel": "gpt-5-nano"},
    )
    assert resp.status_code == 500
    assert "error" in resp.get_json()
