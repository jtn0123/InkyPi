# pyright: reportMissingImports=false
import json
import os


def _write_min_config(path, name="TestCfg"):
    cfg = {
        "name": name,
        "display_type": "mock",
        "resolution": [800, 480],
        "orientation": "horizontal",
        "playlist_config": {"playlists": [], "active_playlist": None},
        "refresh_info": {
            "refresh_time": None,
            "image_hash": None,
            "refresh_type": "Manual Update",
            "plugin_id": ""
        }
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(cfg, f)


def test_env_config_file_takes_precedence(monkeypatch, tmp_path):
    import config as config_mod

    # Arrange
    env_cfg_path = tmp_path / "env_device.json"
    _write_min_config(str(env_cfg_path), name="EnvSelected")

    # Ensure class override points elsewhere to verify env wins
    monkeypatch.setenv("INKYPI_CONFIG_FILE", str(env_cfg_path))
    monkeypatch.setattr(config_mod.Config, "config_file", str(tmp_path / "class_device.json"))

    # Act
    cfg = config_mod.Config()

    # Assert
    assert cfg.get_config("name") == "EnvSelected"


def test_class_override_used_when_env_not_set(monkeypatch, tmp_path):
    import config as config_mod

    # Arrange
    monkeypatch.delenv("INKYPI_CONFIG_FILE", raising=False)
    override_path = tmp_path / "class_device.json"
    _write_min_config(str(override_path), name="ClassSelected")
    monkeypatch.setattr(config_mod.Config, "config_file", str(override_path))

    # Act
    cfg = config_mod.Config()

    # Assert
    assert cfg.get_config("name") == "ClassSelected"


def test_env_mode_dev_uses_device_dev_json(monkeypatch):
    import config as config_mod

    # Arrange – ensure no explicit file set
    monkeypatch.delenv("INKYPI_CONFIG_FILE", raising=False)
    # Hint dev mode via env
    monkeypatch.setenv("INKYPI_ENV", "dev")

    # Act
    cfg = config_mod.Config()

    # Assert – our repository contains a device_dev.json with known name
    assert cfg.config.get("name") in {"InkyPi Development", "InkyPi Dev", "InkyPi"}


def test_bootstrap_when_no_config_found(monkeypatch, tmp_path):
    import config as config_mod

    # Build a temporary project-like structure
    tmp_src = tmp_path / "src_like"
    tmp_install = tmp_path / "install" / "config_base"
    template = tmp_install / "device.json"
    os.makedirs(tmp_src / "config", exist_ok=True)
    os.makedirs(tmp_install, exist_ok=True)
    _write_min_config(str(template), name="Bootstrapped")

    # Point BASE_DIR to our tmp src and clear env/override
    monkeypatch.delenv("INKYPI_CONFIG_FILE", raising=False)
    monkeypatch.delenv("INKYPI_ENV", raising=False)
    monkeypatch.setattr(config_mod.Config, "BASE_DIR", str(tmp_src))
    # Point default config_file to where prod would be (nonexistent yet)
    monkeypatch.setattr(
        config_mod.Config,
        "config_file",
        os.path.join(str(tmp_src), "config", "device.json"),
    )

    # Act – should copy template into src_like/config/device.json
    cfg = config_mod.Config()

    # Assert
    assert cfg.get_config("name") == "Bootstrapped"
    assert os.path.isfile(os.path.join(str(tmp_src), "config", "device.json"))


