def test_plugin_add_config_render_remove_flow(client):
    app = client.application
    device_config = app.config["DEVICE_CONFIG"]
    pm = device_config.get_playlist_manager()

    playlist_name = pm.get_playlist_names()[0]

    # Add plugin to playlist via internal model (UI routes already tested elsewhere)
    added = pm.add_plugin_to_playlist(
        playlist_name,
        {
            "plugin_id": "clock",
            "name": "Lifecycle",
            "plugin_settings": {},
            "refresh": {"interval": 1},
        },
    )
    assert added is True

    # Render the instance
    r = client.post(
        "/display_plugin_instance",
        json={
            "playlist_name": playlist_name,
            "plugin_id": "clock",
            "plugin_instance": "Lifecycle",
        },
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data.get("success") is True

    # Remove the instance
    r2 = client.post(
        "/delete_plugin_instance",
        json={
            "playlist_name": playlist_name,
            "plugin_id": "clock",
            "plugin_instance": "Lifecycle",
        },
    )
    assert r2.status_code == 200
    # Verify it's gone
    pl = pm.get_playlist(playlist_name)
    assert not pl.find_plugin("clock", "Lifecycle")

