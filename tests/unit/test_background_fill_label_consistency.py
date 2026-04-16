# pyright: reportMissingImports=false
"""Tests that image plugins use a consistent 'Background Fill' label (JTN-349 Theme 4)."""


def _get_background_label(plugin_class):
    """Extract the backgroundOption field label from a plugin's schema."""
    plugin = plugin_class({"id": "test", "name": "Test"})
    schema = plugin.build_settings_schema()
    for section in schema.get("sections", []):
        for item in section.get("items", []):
            items = item.get("items", [item])
            for field in items:
                if field.get("name") == "backgroundOption":
                    return field.get("label")
    return None


def test_image_folder_background_fill_label():
    from plugins.image_folder.image_folder import ImageFolder

    assert _get_background_label(ImageFolder) == "Background Fill"


def test_image_upload_background_fill_label():
    from plugins.image_upload.image_upload import ImageUpload

    assert _get_background_label(ImageUpload) == "Background Fill"


def test_image_album_background_fill_label():
    from plugins.image_album.image_album import ImageAlbum

    assert _get_background_label(ImageAlbum) == "Background Fill"


def test_all_image_plugins_same_label():
    """All image plugins with backgroundOption should use the same label."""
    from plugins.image_album.image_album import ImageAlbum
    from plugins.image_folder.image_folder import ImageFolder
    from plugins.image_upload.image_upload import ImageUpload

    labels = {
        "image_folder": _get_background_label(ImageFolder),
        "image_upload": _get_background_label(ImageUpload),
        "image_album": _get_background_label(ImageAlbum),
    }
    unique = {v for v in labels.values() if v is not None}
    assert len(unique) == 1, f"Labels differ across plugins: {labels}"
    assert unique.pop() == "Background Fill"
