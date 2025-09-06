def test_sanitize_config_masks_and_summarizes():
    from config import Config

    cfg = {
        "name": "Device",
        "api_key": "SECRET12345",
        "playlist_config": {
            "active_playlist": "Default",
            "playlists": [
                {
                    "name": "Default",
                    "plugins": [
                        {
                            "plugin_id": "weather",
                            "name": "Weather NYC",
                            "plugin_settings": {"token": "abc", "units": "metric"},
                        }
                    ],
                }
            ],
        },
    }

    sanitized = Config._sanitize_config_for_log(cfg)

    # Secret-like keys masked
    assert sanitized["api_key"] == "***"
    # Playlist summarized; plugin settings not exposed directly
    pl = sanitized["playlist_config"]
    assert pl["active_playlist"] == "Default"
    assert isinstance(pl["playlists"], list)
    assert pl["playlists"][0]["name"] == "Default"
    plugins = pl["playlists"][0]["plugins"]
    assert plugins[0]["plugin_id"] == "weather"
    assert plugins[0]["name"] == "Weather NYC"
    assert "has_settings" in plugins[0]
    assert "plugin_settings" not in plugins[0]


