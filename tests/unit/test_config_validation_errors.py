import json


def test_invalid_orientation_raises_value_error(tmp_path, monkeypatch):
    # Craft a minimal device config with invalid orientation
    bad_cfg = {
        "name": "InkyPi Test",
        "display_type": "mock",
        "resolution": [800, 480],
        "orientation": "diagonal",  # invalid
        "timezone": "UTC",
        "time_format": "24h",
        "plugin_cycle_interval_seconds": 300,
        "image_settings": {
            "saturation": 1.0,
            "brightness": 1.0,
            "sharpness": 1.0,
            "contrast": 1.0,
        },
        "playlist_config": {"playlists": [], "active_playlist": ""},
        "refresh_info": {
            "refresh_time": None,
            "image_hash": None,
            "refresh_type": "Manual Update",
            "plugin_id": "",
        },
    }

    cfg_path = tmp_path / "device.json"
    cfg_path.write_text(json.dumps(bad_cfg))

    # Point Config to this file
    import config as config_mod

    monkeypatch.setattr(config_mod.Config, "config_file", str(cfg_path), raising=True)

    # When jsonschema is missing, fallback validation should catch orientation
    # Force jsonschema to None
    monkeypatch.setattr(config_mod, "jsonschema", None, raising=True)

    # Attempt to construct Config should raise due to validation
    try:
        _ = config_mod.Config()
        raised = False
    except ValueError as e:
        raised = True
        msg = str(e)
        assert "orientation" in msg
        assert "invalid value" in msg
    assert raised

