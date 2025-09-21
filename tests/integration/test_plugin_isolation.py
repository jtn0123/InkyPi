def test_failing_plugin_does_not_block_successful_plugin(client, monkeypatch):
    # Arrange playlist with two plugins: one will error, one succeeds
    app = client.application
    device_config = app.config["DEVICE_CONFIG"]
    pm = device_config.get_playlist_manager()

    # Ensure default playlist exists
    names = pm.get_playlist_names()
    playlist = pm.get_playlist(names[0])

    # Add two plugin instances (use existing plugins in repo if possible)
    playlist.add_plugin({
        "plugin_id": "ai_text",
        "name": "Failer",
        "plugin_settings": {"text": "bad"},
        "refresh": {"interval": 1},
    })
    playlist.add_plugin({
        "plugin_id": "clock",
        "name": "OK",
        "plugin_settings": {},
        "refresh": {"interval": 1},
    })

    # Force ai_text plugin to raise during generate_image
    import plugins.ai_text.ai_text as ai_text_mod

    def boom(settings, cfg):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(ai_text_mod.AIText, "generate_image", staticmethod(boom), raising=True)

    # Trigger display of the OK plugin explicitly to simulate cycle behavior
    resp = client.post(
        "/display_plugin_instance",
        json={
            "playlist_name": playlist.name,
            "plugin_id": "clock",
            "plugin_instance": "OK",
        },
    )
    # The success path should still work despite the other plugin being broken
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get("success") is True

