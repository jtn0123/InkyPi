import random

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


def test_generate_image_invalid_background_color_falls_back(
    monkeypatch, device_config_dev, tmp_path
):
    from plugins.image_folder.image_folder import ImageFolder

    folder = tmp_path / "imgs"
    folder.mkdir()
    _make_img(folder / "img_0.jpg", size=(320, 240))
    monkeypatch.setattr(random, "choice", lambda seq: seq[0], raising=True)

    plugin = ImageFolder(
        {"id": "image_folder", "class": "ImageFolder", "name": "Image Folder"}
    )
    img = plugin.generate_image(
        {
            "folder_path": str(folder),
            "padImage": "true",
            "backgroundOption": "color",
            "backgroundColor": "notacolor",
        },
        device_config_dev,
    )
    assert img is not None


def test_image_folder_background_option_has_default_blur_in_schema():
    """JTN-632: The Background Fill radio_segment must declare a default so
    that DRAFT renders pre-select one option (Blur). Without a default,
    neither radio is checked and users can save in an indeterminate state."""
    from plugins.image_folder.image_folder import ImageFolder

    sch = ImageFolder({"id": "image_folder"}).build_settings_schema()

    def _find_field(obj, name):
        if isinstance(obj, dict):
            if obj.get("name") == name:
                return obj
            for v in obj.values():
                found = _find_field(v, name)
                if found is not None:
                    return found
        elif isinstance(obj, list):
            for item in obj:
                found = _find_field(item, name)
                if found is not None:
                    return found
        return None

    bg = _find_field(sch, "backgroundOption")
    assert bg is not None
    assert bg.get("default") == "blur", (
        "image_folder backgroundOption must default to 'blur' so the radio "
        "group has a pre-selected option in DRAFT mode (JTN-632)"
    )


def test_image_folder_draft_page_preselects_blur_radio(client):
    """JTN-632: Rendering /plugin/image_folder with no saved instance
    (DRAFT mode) must pre-check exactly one Background Fill radio option."""
    import re

    resp = client.get("/plugin/image_folder")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")

    radios = re.findall(
        r'<input[^>]*name="backgroundOption"[^>]*>',
        body,
        flags=re.IGNORECASE | re.DOTALL,
    )
    assert len(radios) >= 2, "expected at least two backgroundOption radios"
    checked_radios = [r for r in radios if re.search(r"\bchecked\b", r)]
    assert len(checked_radios) == 1, (
        f"expected exactly one backgroundOption radio to be pre-checked in "
        f"DRAFT mode, found {len(checked_radios)} (JTN-632)"
    )
    assert re.search(
        r'value="blur"', checked_radios[0]
    ), "the pre-checked backgroundOption radio must be 'blur' (JTN-632)"
