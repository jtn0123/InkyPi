import json
import os


def _write_min_config(path, name="Cfg"):
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


def test_get_plugin_image_path(monkeypatch, tmp_path):
    import config as config_mod

    # Use temp device.json
    cfg_path = tmp_path / "device.json"
    _write_min_config(str(cfg_path), name="ImgPathTest")
    monkeypatch.setattr(config_mod.Config, "config_file", str(cfg_path))

    cfg = config_mod.Config()
    # Should build a safe plugin image path
    path = cfg.get_plugin_image_path("weather", "My Instance")
    assert path.endswith("weather_My_Instance.png")


def test_read_plugins_list_handles_missing_dir(monkeypatch, tmp_path):
    import config as config_mod

    # Point BASE_DIR to temp that lacks plugins dir
    monkeypatch.setattr(config_mod.Config, "BASE_DIR", str(tmp_path))
    # Provide a minimal valid device.json for constructor
    cfg_path = tmp_path / "config" / "device.json"
    _write_min_config(str(cfg_path))
    monkeypatch.setattr(config_mod.Config, "config_file", str(cfg_path))

    cfg = config_mod.Config()
    assert cfg.get_plugins() == []


def test_determine_config_path_bootstrap_failure(monkeypatch, tmp_path):
    import config as config_mod

    # Point BASE_DIR to isolated tmp src
    src_dir = tmp_path / "isolated_src"
    os.makedirs(src_dir, exist_ok=True)
    monkeypatch.setattr(config_mod.Config, "BASE_DIR", str(src_dir))
    # Ensure no env/class override
    monkeypatch.delenv("INKYPI_CONFIG_FILE", raising=False)
    monkeypatch.delenv("INKYPI_ENV", raising=False)
    # Simulate missing install template so bootstrap fails
    # Also ensure config dir not creatable by mocking shutil.copyfile to raise
    import shutil

    def _boom(*_a, **_kw):
        raise OSError("copy failed")

    monkeypatch.setattr(config_mod.shutil, "copyfile", _boom)

    # Expect a RuntimeError when constructor tries to resolve config path
    try:
        _ = config_mod.Config()
        assert False, "Expected RuntimeError due to bootstrap failure"
    except RuntimeError as ex:  # noqa: F841
        # Pass: raised as expected
        assert True


