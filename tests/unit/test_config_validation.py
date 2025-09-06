import json
import os
import pytest


def _patch_paths_to_tmp(config_mod, tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod.Config, "current_image_file", str(tmp_path / "current_image.png"))
    monkeypatch.setattr(config_mod.Config, "processed_image_file", str(tmp_path / "processed_image.png"))
    monkeypatch.setattr(config_mod.Config, "plugin_image_dir", str(tmp_path / "plugins"))
    monkeypatch.setattr(config_mod.Config, "history_image_dir", str(tmp_path / "history"))
    os.makedirs(str(tmp_path / "plugins"), exist_ok=True)
    os.makedirs(str(tmp_path / "history"), exist_ok=True)


def test_device_config_valid_ok(device_config_dev):
    # Fixture already constructs a valid Config; validation should pass implicitly
    assert device_config_dev.get_config("orientation") in ("horizontal", "vertical")


def test_device_config_invalid_orientation_raises(tmp_path, monkeypatch):
    cfg = {
        "name": "InkyPi Test",
        "display_type": "mock",
        "resolution": [800, 480],
        "orientation": "diagonal",  # invalid against schema enum
        "plugin_cycle_interval_seconds": 300,
        "image_settings": {"saturation": 1.0, "brightness": 1.0, "sharpness": 1.0, "contrast": 1.0},
        "playlist_config": {"playlists": [], "active_playlist": ""},
        "refresh_info": {"refresh_time": None, "image_hash": None, "refresh_type": "Manual Update", "plugin_id": ""},
    }
    config_file = tmp_path / "device.json"
    config_file.write_text(json.dumps(cfg))

    import config as config_mod

    monkeypatch.setattr(config_mod.Config, "config_file", str(config_file))
    _patch_paths_to_tmp(config_mod, tmp_path, monkeypatch)

    with pytest.raises(ValueError) as ei:
        config_mod.Config()
    # Error should include our prefix and hint at orientation
    msg = str(ei.value)
    assert "device.json failed schema validation" in msg
    assert "orientation" in msg


