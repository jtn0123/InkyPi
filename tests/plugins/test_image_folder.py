import random

import pytest
from PIL import Image

def _make_img(path: str, size=(64, 48), color=(200, 100, 50)):
    img = Image.new("RGB", size, color)
    img.save(path)

def test_list_files_in_folder_filters_hidden_and_non_images(tmp_path):
    from plugins.image_folder.image_folder import list_files_in_folder

    # files
    p1 = tmp_path / "a.jpg"
    p2 = tmp_path / "b.PNG"
    p3 = tmp_path / "c.txt"
    p4 = tmp_path / ".hidden.jpg"
    _make_img(p1)
    _make_img(p2)
    p3.write_text("nope")
    _make_img(p4)

    result = list_files_in_folder(str(tmp_path))
    assert str(p1) in result
    assert str(p2) in result
    assert str(p3) not in result
    assert str(p4) not in result

def test_generate_image_happy(monkeypatch, device_config_dev, tmp_path):
    from plugins.image_folder.image_folder import ImageFolder

    folder = tmp_path / "imgs"
    folder.mkdir()
    # create a few images
    for i in range(3):
        _make_img(folder / f"img_{i}.jpg", size=(320 + i * 10, 240))

    # make random deterministic
    monkeypatch.setattr(random, "choice", lambda seq: seq[0], raising=True)

    plugin = ImageFolder(
        {"id": "image_folder", "class": "ImageFolder", "name": "Image Folder"}
    )
    img = plugin.generate_image(
        {"folder_path": str(folder), "padImage": False}, device_config_dev
    )
    assert img is not None
    assert isinstance(img, Image.Image)

def test_generate_image_errors(tmp_path, device_config_dev):
    from plugins.image_folder.image_folder import ImageFolder

    plugin = ImageFolder(
        {"id": "image_folder", "class": "ImageFolder", "name": "Image Folder"}
    )

    # missing path
    try:
        plugin.generate_image({}, device_config_dev)
        assert False, "expected error"
    except RuntimeError as e:
        assert "Folder path is required" in str(e)

    # missing folder
    try:
        plugin.generate_image(
            {"folder_path": str(tmp_path / "nope")}, device_config_dev
        )
        assert False
    except RuntimeError as e:
        assert "Folder does not exist" in str(e)

    # not a dir
    file_path = tmp_path / "file.jpg"
    _make_img(file_path)
    try:
        plugin.generate_image({"folder_path": str(file_path)}, device_config_dev)
        assert False
    except RuntimeError as e:
        assert "not a directory" in str(e)

    # empty dir
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    try:
        plugin.generate_image({"folder_path": str(empty_dir)}, device_config_dev)
        assert False
    except RuntimeError as e:
        assert "No image files found" in str(e)

def test_image_folder_initializes_without_name_error():
    """Plugin should be importable and instantiable without NameError."""
    from plugins.image_folder.image_folder import ImageFolder

    plugin = ImageFolder(
        {"id": "image_folder", "class": "ImageFolder", "name": "Image Folder"}
    )
    assert plugin is not None
