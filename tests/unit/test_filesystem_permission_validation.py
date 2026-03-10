import os
import shutil

from PIL import Image


def test_config_init_tolerates_preview_copy_permission_error(monkeypatch, tmp_path):
    import config as config_mod

    config_path = tmp_path / "device.json"
    config_path.write_text(
        """
        {
          "name": "Permission Test",
          "display_type": "mock",
          "resolution": [800, 480],
          "orientation": "horizontal",
          "playlist_config": {"playlists": [], "active_playlist": ""},
          "refresh_info": {
            "refresh_time": null,
            "image_hash": null,
            "refresh_type": "Manual Update",
            "plugin_id": ""
          }
        }
        """,
        encoding="utf-8",
    )

    monkeypatch.setattr(config_mod.Config, "config_file", str(config_path))
    monkeypatch.setattr(shutil, "copyfile", lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError("no write")))

    cfg = config_mod.Config()
    assert cfg.get_config("name") == "Permission Test"


def test_display_manager_tolerates_readonly_preview_paths(device_config_dev, monkeypatch):
    from display.display_manager import DisplayManager

    manager = DisplayManager(device_config_dev)
    render_calls = {"count": 0}

    def fake_render(img, image_settings=None):
        render_calls["count"] += 1

    original_save = Image.Image.save

    def conditional_save(self, fp, *args, **kwargs):
        if str(fp) == device_config_dev.current_image_file:
            return original_save(self, fp, *args, **kwargs)
        raise PermissionError("readonly")

    monkeypatch.setattr(manager.display, "display_image", fake_render, raising=True)
    monkeypatch.setattr(Image.Image, "save", conditional_save, raising=True)

    metrics = manager.display_image(Image.new("RGB", (64, 48), "white"))
    assert render_calls["count"] == 1
    assert metrics["display_driver"] == manager.display.__class__.__name__


def test_history_clear_returns_500_on_permission_error(client, device_config_dev, tmp_path, monkeypatch):
    history_dir = device_config_dev.history_image_dir
    image_path = os.path.join(history_dir, "display_20250101_000000.png")
    Image.new("RGB", (10, 10), "white").save(image_path)

    monkeypatch.setattr(
        os,
        "remove",
        lambda path: (_ for _ in ()).throw(PermissionError("denied")),
    )

    response = client.post("/history/clear")
    assert response.status_code == 500
    assert response.get_json()["success"] is False


def test_preview_returns_404_when_preview_files_missing(client, device_config_dev):
    for path in (device_config_dev.processed_image_file, device_config_dev.current_image_file):
        if os.path.exists(path):
            os.remove(path)

    response = client.get("/preview")
    assert response.status_code == 404
