# pyright: reportMissingImports=false
"""Tests for server-side plugin settings validation (JTN-187)."""


def test_save_rejects_missing_required_fields(client):
    """Saving plugin settings with empty required fields should return 400."""
    resp = client.post(
        "/save_plugin_settings",
        data={"plugin_id": "image_folder", "folder_path": ""},
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert "Required" in data.get("error", "")
    assert "Folder Path" in data.get("error", "")


def test_save_accepts_valid_required_fields(client, tmp_path):
    """Saving with all required fields filled should not return 400."""
    from PIL import Image

    folder = tmp_path / "test-images"
    folder.mkdir()
    # JTN-355: folder must actually exist and contain at least one image
    Image.new("RGB", (8, 8), "white").save(folder / "sample.png")

    resp = client.post(
        "/save_plugin_settings",
        data={"plugin_id": "image_folder", "folder_path": str(folder)},
    )
    assert resp.status_code != 400


def test_save_rejects_whitespace_only_required_fields(client):
    """Whitespace-only values should be treated as empty for required fields."""
    resp = client.post(
        "/save_plugin_settings",
        data={"plugin_id": "image_folder", "folder_path": "   "},
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert "Required" in data.get("error", "")


def test_save_alias_rejects_missing_required_fields(client):
    """The alias save route also validates required fields."""
    resp = client.post(
        "/plugin/image_folder/save",
        data={"folder_path": ""},
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert "Required" in data.get("error", "")


def test_save_skips_validation_for_plugin_without_schema(client):
    """Plugins that do not define build_settings_schema should not fail validation."""
    # clock plugin exists but we just verify it does not 400 due to missing schema
    resp = client.post(
        "/save_plugin_settings",
        data={"plugin_id": "clock"},
    )
    # Should succeed (200) — not a validation error
    assert resp.status_code == 200


def test_update_instance_rejects_missing_required_fields(client, device_config_dev):
    """Updating an existing plugin instance validates required fields."""
    # Create an instance first via save
    pm = device_config_dev.get_playlist_manager()
    if not pm.get_playlist("Default"):
        pm.add_playlist("Default")
    playlist = pm.get_playlist("Default")
    playlist.add_plugin(
        {
            "plugin_id": "image_folder",
            "name": "test_instance",
            "plugin_settings": {"folder_path": "/tmp/existing"},
            "refresh": {"interval": 300},
        }
    )
    device_config_dev.write_config()

    resp = client.put(
        "/update_plugin_instance/test_instance",
        data={"plugin_id": "image_folder", "folder_path": ""},
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert "Required" in data.get("error", "")


def test_update_instance_accepts_valid_required_fields(
    client, device_config_dev, tmp_path
):
    """Updating an existing instance with valid required fields should succeed."""
    from PIL import Image

    # JTN-355: folder must actually exist and contain at least one image
    new_folder = tmp_path / "new-path"
    new_folder.mkdir()
    Image.new("RGB", (8, 8), "white").save(new_folder / "sample.png")

    pm = device_config_dev.get_playlist_manager()
    if not pm.get_playlist("Default"):
        pm.add_playlist("Default")
    playlist = pm.get_playlist("Default")
    playlist.add_plugin(
        {
            "plugin_id": "image_folder",
            "name": "valid_instance",
            "plugin_settings": {"folder_path": str(tmp_path / "old")},
            "refresh": {"interval": 300},
        }
    )
    device_config_dev.write_config()

    resp = client.put(
        "/update_plugin_instance/valid_instance",
        data={"plugin_id": "image_folder", "folder_path": str(new_folder)},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get("success") is True
