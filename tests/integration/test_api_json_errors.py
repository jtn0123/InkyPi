# pyright: reportMissingImports=false


def test_update_now_surfaces_plugin_error_json(client, monkeypatch):
    # Make plugin raise
    import plugins.ai_text.ai_text as ai_text_mod

    def boom(self, settings, device_config):
        raise RuntimeError("boom")

    monkeypatch.setattr(ai_text_mod.AIText, "generate_image", boom, raising=True)

    resp = client.post(
        "/update_now",
        data={"plugin_id": "ai_text", "title": "T", "textModel": "gpt-4o", "textPrompt": "hi"},
    )
    assert resp.status_code == 500
    data = resp.get_json()
    assert isinstance(data, dict)
    assert "error" in data


def test_save_plugin_settings_error_json(client, flask_app, monkeypatch):
    # Simulate a config write failure so endpoint returns JSON error
    dc = flask_app.config["DEVICE_CONFIG"]
    def boom_update_value(*args, **kwargs):
        raise RuntimeError("boom")
    monkeypatch.setattr(dc, "update_value", boom_update_value, raising=True)

    resp = client.post("/save_plugin_settings", data={"plugin_id": "ai_text"})
    assert resp.status_code == 500
    assert "error" in resp.get_json()


