"""Tests to achieve 100% coverage of config.py

Specifically targeting previously uncovered lines:
- Lines 107-108: INKYPI_ENV environment variable handling
- Lines 149-151: _validate_device_config call path
"""

import json
import os
import pytest


def test_inkypi_env_dev_selects_dev_config(tmp_path, monkeypatch):
    """Test that INKYPI_ENV=dev causes dev config selection (lines 107-112)."""
    # Create a dev config file
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    dev_config = config_dir / "device_dev.json"

    cfg_data = {
        "name": "InkyPi Dev",
        "display_type": "mock",
        "resolution": [800, 480],
        "orientation": "horizontal",
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
    dev_config.write_text(json.dumps(cfg_data))

    import config as config_mod

    # Point BASE_DIR to our tmp location
    monkeypatch.setattr(config_mod.Config, "BASE_DIR", str(tmp_path))
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

    # Set INKYPI_ENV=dev
    monkeypatch.setenv("INKYPI_ENV", "dev")

    # Create Config - should select dev_config due to INKYPI_ENV
    cfg = config_mod.Config()

    # Verify it loaded the dev config
    assert cfg.get_config("name") == "InkyPi Dev"
    assert "dev" in cfg.config_file.lower()


def test_flask_env_development_fallback(tmp_path, monkeypatch):
    """Test that FLASK_ENV=development also triggers dev config (lines 108-113)."""
    # Create a dev config file
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    dev_config = config_dir / "device_dev.json"

    cfg_data = {
        "name": "InkyPi Dev Flask",
        "display_type": "mock",
        "resolution": [800, 480],
        "orientation": "horizontal",
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
    dev_config.write_text(json.dumps(cfg_data))

    import config as config_mod

    monkeypatch.setattr(config_mod.Config, "BASE_DIR", str(tmp_path))
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

    # Set FLASK_ENV=development (but not INKYPI_ENV)
    monkeypatch.delenv("INKYPI_ENV", raising=False)
    monkeypatch.setenv("FLASK_ENV", "development")

    cfg = config_mod.Config()

    assert cfg.get_config("name") == "InkyPi Dev Flask"


def test_validate_device_config_called_on_read(tmp_path, monkeypatch):
    """Test that _validate_device_config is invoked when reading config (line 151)."""
    # Create a valid config
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_file = config_dir / "device.json"

    cfg_data = {
        "name": "InkyPi Validated",
        "display_type": "mock",
        "resolution": [800, 480],
        "orientation": "horizontal",
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
    config_file.write_text(json.dumps(cfg_data))

    import config as config_mod

    monkeypatch.setattr(config_mod.Config, "BASE_DIR", str(tmp_path))
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

    # Track if _validate_device_config was called
    validate_called = {"count": 0}
    original_validate = config_mod.Config._validate_device_config

    def track_validate(self, config_dict):
        validate_called["count"] += 1
        return original_validate(self, config_dict)

    monkeypatch.setattr(
        config_mod.Config, "_validate_device_config", track_validate
    )

    # Create Config - should call validate during read_config
    cfg = config_mod.Config()

    # Verify validation was called
    assert validate_called["count"] > 0, "_validate_device_config should be called"


def test_validation_with_jsonschema_available(tmp_path, monkeypatch):
    """Test validation path when jsonschema is available (covers validation logic)."""
    import shutil

    # Create a config with a subtle schema violation
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_file = config_dir / "device.json"

    # Copy schema files to tmp location
    schemas_dir = config_dir / "schemas"
    schemas_dir.mkdir()

    import config as config_mod

    # Copy the actual schema file
    src_schema = os.path.join(
        config_mod.Config.BASE_DIR, "config", "schemas", "device_config.schema.json"
    )
    if os.path.exists(src_schema):
        shutil.copy(src_schema, str(schemas_dir / "device_config.schema.json"))

    # Invalid: orientation should be 'horizontal' or 'vertical', not 'sideways'
    cfg_data = {
        "name": "InkyPi Invalid",
        "display_type": "mock",
        "resolution": [800, 480],
        "orientation": "sideways",  # Invalid!
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
    config_file.write_text(json.dumps(cfg_data))

    monkeypatch.setattr(config_mod.Config, "BASE_DIR", str(tmp_path))
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

    # Should raise ValueError due to schema validation (if schema exists)
    if os.path.exists(src_schema):
        with pytest.raises(ValueError, match="schema validation"):
            config_mod.Config()
    else:
        # If schema doesn't exist, just verify it loads (skips validation)
        cfg = config_mod.Config()
        assert cfg is not None


def test_validation_without_jsonschema(tmp_path, monkeypatch):
    """Test that config loads when jsonschema is not available."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_file = config_dir / "device.json"

    cfg_data = {
        "name": "InkyPi No Schema",
        "display_type": "mock",
        "resolution": [800, 480],
        "orientation": "horizontal",
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
    config_file.write_text(json.dumps(cfg_data))

    import config as config_mod

    monkeypatch.setattr(config_mod.Config, "BASE_DIR", str(tmp_path))
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

    # Temporarily disable jsonschema
    original_jsonschema = config_mod.jsonschema
    monkeypatch.setattr(config_mod, "jsonschema", None)

    # Should still load without validation
    cfg = config_mod.Config()
    assert cfg.get_config("name") == "InkyPi No Schema"

    # Restore
    monkeypatch.setattr(config_mod, "jsonschema", original_jsonschema)


def test_env_mode_with_whitespace(tmp_path, monkeypatch):
    """Test that INKYPI_ENV with whitespace is handled correctly (strip())."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    dev_config = config_dir / "device_dev.json"

    cfg_data = {
        "name": "InkyPi Dev Whitespace",
        "display_type": "mock",
        "resolution": [800, 480],
        "orientation": "horizontal",
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
    dev_config.write_text(json.dumps(cfg_data))

    import config as config_mod

    monkeypatch.setattr(config_mod.Config, "BASE_DIR", str(tmp_path))
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

    # Set INKYPI_ENV with whitespace
    monkeypatch.setenv("INKYPI_ENV", "  dev  ")

    cfg = config_mod.Config()
    assert cfg.get_config("name") == "InkyPi Dev Whitespace"
