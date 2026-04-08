import json
import os

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _patch_paths_to_tmp(config_mod, tmp_path, monkeypatch):
    monkeypatch.setattr(
        config_mod.Config, "current_image_file", str(tmp_path / "current_image.png")
    )
    monkeypatch.setattr(
        config_mod.Config, "processed_image_file", str(tmp_path / "processed_image.png")
    )
    monkeypatch.setattr(
        config_mod.Config, "plugin_image_dir", str(tmp_path / "plugins")
    )
    monkeypatch.setattr(
        config_mod.Config, "history_image_dir", str(tmp_path / "history")
    )
    os.makedirs(str(tmp_path / "plugins"), exist_ok=True)
    os.makedirs(str(tmp_path / "history"), exist_ok=True)


def _write_min_config(path, name="Original"):
    cfg = {
        "name": name,
        "display_type": "mock",
        "resolution": [800, 480],
        "orientation": "horizontal",
        "playlist_config": {"playlists": [], "active_playlist": ""},
        "refresh_info": {
            "refresh_time": None,
            "image_hash": None,
            "refresh_type": "Manual Update",
            "plugin_id": "",
        },
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(cfg, f)


# ---------------------------------------------------------------------------
# Schema validation — valid config
# ---------------------------------------------------------------------------


def test_device_config_valid_ok(device_config_dev):
    # Fixture already constructs a valid Config; validation should pass implicitly
    assert device_config_dev.get_config("orientation") in ("horizontal", "vertical")


# ---------------------------------------------------------------------------
# Schema validation — invalid orientation (jsonschema path)
# ---------------------------------------------------------------------------


def test_device_config_invalid_orientation_raises(tmp_path, monkeypatch):
    cfg = {
        "name": "InkyPi Test",
        "display_type": "mock",
        "resolution": [800, 480],
        "orientation": "diagonal",  # invalid against schema enum
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


# ---------------------------------------------------------------------------
# Schema validation — invalid orientation (fallback path, no jsonschema)
# ---------------------------------------------------------------------------


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
    import utils.config_schema as schema_mod

    monkeypatch.setattr(config_mod.Config, "config_file", str(cfg_path), raising=True)

    # When jsonschema is missing, fallback validation should catch orientation.
    # Patch the module-level binding in config_schema (the validation now lives there).
    monkeypatch.setattr(schema_mod, "jsonschema", None, raising=True)

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


# ---------------------------------------------------------------------------
# Config sanitizer — masks secrets, summarizes playlist settings
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Bootstrap idempotency — existing config must not be overwritten
# ---------------------------------------------------------------------------


def test_bootstrap_idempotent_when_prod_exists(monkeypatch, tmp_path):
    import config as config_mod

    # Create a src-like structure with existing device.json
    tmp_src = tmp_path / "src_like"
    os.makedirs(tmp_src / "config", exist_ok=True)
    prod_path = tmp_src / "config" / "device.json"
    _write_min_config(str(prod_path), name="KeepMe")

    # Provide a different template content to ensure it would differ
    tmp_install = tmp_path / "install" / "config_base"
    os.makedirs(tmp_install, exist_ok=True)
    template = tmp_install / "device.json"
    _write_min_config(str(template), name="TemplateShouldNotOverwrite")

    # Point BASE_DIR and defaults
    monkeypatch.setattr(config_mod.Config, "BASE_DIR", str(tmp_src))
    monkeypatch.delenv("INKYPI_CONFIG_FILE", raising=False)
    monkeypatch.delenv("INKYPI_ENV", raising=False)
    monkeypatch.setattr(
        config_mod.Config,
        "config_file",
        os.path.join(str(tmp_src), "config", "device.json"),
    )

    cfg = config_mod.Config()
    # Should preserve the existing name, not overwrite with template
    assert cfg.get_config("name") == "KeepMe"
    assert os.path.isfile(os.path.join(str(tmp_src), "config", "device.json"))
