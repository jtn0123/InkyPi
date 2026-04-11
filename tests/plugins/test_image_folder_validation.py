# pyright: reportMissingImports=false
"""JTN-355: validate_settings for the Image Folder plugin.

The prior behavior silently accepted any ``folder_path`` at save time; bad
values only surfaced later when ``generate_image`` ran at refresh time,
making the failure hard to trace back to the save action.
"""

from PIL import Image


def _make_img(path, size=(32, 24), color=(100, 150, 200)):
    Image.new("RGB", size, color).save(path)


def test_validate_settings_missing_path_returns_error():
    from plugins.image_folder.image_folder import ImageFolder

    plugin = ImageFolder({"id": "image_folder"})
    err = plugin.validate_settings({})
    assert err is not None
    assert "required" in err.lower()


def test_validate_settings_empty_path_returns_error():
    from plugins.image_folder.image_folder import ImageFolder

    plugin = ImageFolder({"id": "image_folder"})
    err = plugin.validate_settings({"folder_path": ""})
    assert err is not None
    assert "required" in err.lower()


def test_validate_settings_whitespace_path_returns_error():
    from plugins.image_folder.image_folder import ImageFolder

    plugin = ImageFolder({"id": "image_folder"})
    err = plugin.validate_settings({"folder_path": "   "})
    assert err is not None
    assert "required" in err.lower()


def test_validate_settings_nonexistent_path_returns_error(tmp_path):
    from plugins.image_folder.image_folder import ImageFolder

    plugin = ImageFolder({"id": "image_folder"})
    bogus = tmp_path / "does" / "not" / "exist"
    err = plugin.validate_settings({"folder_path": str(bogus)})
    assert err is not None
    assert "exist" in err.lower() or "readable" in err.lower()


def test_validate_settings_path_is_file_returns_error(tmp_path):
    from plugins.image_folder.image_folder import ImageFolder

    plugin = ImageFolder({"id": "image_folder"})
    # pass a file path, not a directory
    f = tmp_path / "not_a_dir.txt"
    f.write_text("hello")
    err = plugin.validate_settings({"folder_path": str(f)})
    assert err is not None
    assert "exist" in err.lower() or "readable" in err.lower()


def test_validate_settings_empty_folder_returns_error(tmp_path):
    from plugins.image_folder.image_folder import ImageFolder

    plugin = ImageFolder({"id": "image_folder"})
    empty = tmp_path / "empty"
    empty.mkdir()
    err = plugin.validate_settings({"folder_path": str(empty)})
    assert err is not None
    assert "no image" in err.lower()


def test_validate_settings_folder_with_only_non_images_returns_error(tmp_path):
    from plugins.image_folder.image_folder import ImageFolder

    plugin = ImageFolder({"id": "image_folder"})
    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "readme.txt").write_text("not an image")
    (folder / "notes.md").write_text("also not an image")
    err = plugin.validate_settings({"folder_path": str(folder)})
    assert err is not None
    assert "no image" in err.lower()


def test_validate_settings_folder_with_one_png_returns_none(tmp_path):
    from plugins.image_folder.image_folder import ImageFolder

    plugin = ImageFolder({"id": "image_folder"})
    folder = tmp_path / "pics"
    folder.mkdir()
    _make_img(folder / "a.png")
    assert plugin.validate_settings({"folder_path": str(folder)}) is None


def test_validate_settings_folder_with_mixed_files_returns_none(tmp_path):
    from plugins.image_folder.image_folder import ImageFolder

    plugin = ImageFolder({"id": "image_folder"})
    folder = tmp_path / "mixed"
    folder.mkdir()
    (folder / "readme.txt").write_text("text file")
    _make_img(folder / "photo.jpg")
    assert plugin.validate_settings({"folder_path": str(folder)}) is None


def test_validate_settings_nested_images_returns_none(tmp_path):
    from plugins.image_folder.image_folder import ImageFolder

    plugin = ImageFolder({"id": "image_folder"})
    folder = tmp_path / "nested"
    sub = folder / "subfolder"
    sub.mkdir(parents=True)
    _make_img(sub / "inner.png")
    assert plugin.validate_settings({"folder_path": str(folder)}) is None


def test_save_plugin_settings_rejects_missing_folder(client):
    """JTN-355: POST /save_plugin_settings with bad path returns 4xx."""
    data = {
        "plugin_id": "image_folder",
        "folder_path": "/definitely/not/a/real/path/for/jtn355",
        "padImage": "false",
        "backgroundOption": "blur",
    }
    resp = client.post("/save_plugin_settings", data=data)
    assert resp.status_code == 400
    body = resp.get_json() or {}
    assert body.get("success") is False
    msg = body.get("error") or body.get("message") or ""
    assert "exist" in msg.lower() or "readable" in msg.lower()


def test_save_plugin_settings_rejects_empty_folder(client, tmp_path):
    """JTN-355: POST /save_plugin_settings with an empty folder returns 4xx."""
    empty = tmp_path / "empty_dir"
    empty.mkdir()
    data = {
        "plugin_id": "image_folder",
        "folder_path": str(empty),
        "padImage": "false",
        "backgroundOption": "blur",
    }
    resp = client.post("/save_plugin_settings", data=data)
    assert resp.status_code == 400
    body = resp.get_json() or {}
    assert body.get("success") is False
    msg = body.get("error") or body.get("message") or ""
    assert "no image" in msg.lower()


def test_save_plugin_settings_accepts_folder_with_image(client, tmp_path):
    """JTN-355: valid folder with at least one image saves successfully."""
    folder = tmp_path / "valid_imgs"
    folder.mkdir()
    _make_img(folder / "one.png")
    data = {
        "plugin_id": "image_folder",
        "folder_path": str(folder),
        "padImage": "false",
        "backgroundOption": "blur",
    }
    resp = client.post("/save_plugin_settings", data=data)
    assert resp.status_code == 200
    body = resp.get_json() or {}
    assert body.get("success") is True
