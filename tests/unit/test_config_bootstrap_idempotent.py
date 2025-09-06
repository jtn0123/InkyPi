import json
import os


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


