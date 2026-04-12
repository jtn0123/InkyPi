# pyright: reportMissingImports=false
import tempfile
from io import BytesIO

import pytest
from PIL import Image

import plugins.image_upload.image_upload as _image_upload_mod


@pytest.fixture(autouse=True)
def _patch_upload_dir(monkeypatch):
    """Point _get_upload_dir to the system temp directory so that tests using
    tempfile.NamedTemporaryFile pass path validation."""
    monkeypatch.setattr(
        _image_upload_mod, "_get_upload_dir", lambda: tempfile.gettempdir()
    )


def build_upload(name: str, content: bytes, content_type: str = "image/png"):
    class F:
        def __init__(self, n, b, ct):
            self.filename = n
            self._b = b
            self.content_type = ct
            self._pos = 0

            class S:
                def __init__(self, outer):
                    self._outer = outer

                def tell(self):
                    return self._outer._pos

            self.stream = S(self)

        def read(self):
            return self._b

        def seek(self, pos):
            self._pos = pos

        def save(self, fp):
            with open(fp, "wb") as f:
                f.write(self._b)

    return F(name, content, content_type)


class MultiDict:
    def __init__(self, items):
        self._items = items

    def items(self, multi=False):
        return self._items

    def keys(self):
        return [k for (k, _v) in self._items]


def test_image_upload_success(client, monkeypatch, device_config_dev, tmp_path):
    # Ensure request.files handling saves and plugin loads correctly
    buf = BytesIO()
    Image.new("RGB", (100, 50), "white").save(buf, format="PNG")
    content = buf.getvalue()

    data = {
        "plugin_id": "image_upload",
        "padImage": "false",
    }

    upload = build_upload("test.png", content, "image/png")

    # Intercept handle_request_files to feed our upload through the real validator
    import utils.app_utils as app_utils

    # Re-patch _get_upload_dir to match the actual upload path used by
    # handle_request_files so that path validation accepts saved files.
    real_upload_dir = app_utils.resolve_path("static/images/saved")
    monkeypatch.setattr(_image_upload_mod, "_get_upload_dir", lambda: real_upload_dir)

    def fake_handle_request_files(request_files, form_data=None):
        if form_data is None:
            form_data = {}
        return app_utils.handle_request_files(
            MultiDict([("imageFiles[]", upload)]), form_data
        )

    import blueprints.plugin as plugin_bp_mod

    monkeypatch.setattr(
        plugin_bp_mod, "handle_request_files", fake_handle_request_files, raising=True
    )

    resp = client.post("/update_now", data=data)
    assert resp.status_code == 200


def test_image_upload_rejects_non_image(client, monkeypatch):
    bad_content = b"%PDF-1.4 Not an image"

    upload = build_upload("doc.pdf", bad_content, "application/pdf")

    import utils.app_utils as app_utils

    def fake_handle_request_files(request_files, form_data=None):
        # Should skip non-allowed extension and thus not crash; return empty map
        if form_data is None:
            form_data = {}
        return app_utils.handle_request_files(
            MultiDict([("imageFiles[]", upload)]), form_data
        )

    import blueprints.plugin as plugin_bp_mod

    monkeypatch.setattr(
        plugin_bp_mod, "handle_request_files", fake_handle_request_files, raising=True
    )

    resp = client.post("/update_now", data={"plugin_id": "image_upload"})
    # No files processed; plugin will error due to no images provided
    assert resp.status_code == 400


def test_image_upload_rejects_oversize(client, monkeypatch):
    # 11MB fake PNG-like bytes (not decodable)
    big = b"\x89PNG\r\n" + b"0" * (11 * 1024 * 1024)

    upload = build_upload("huge.png", big, "image/png")

    monkeypatch.setenv("MAX_UPLOAD_BYTES", str(1024 * 1024))  # 1MB limit

    import utils.app_utils as app_utils

    def fake_handle_request_files(request_files, form_data=None):
        if form_data is None:
            form_data = {}
        return app_utils.handle_request_files(
            MultiDict([("imageFiles[]", upload)]), form_data
        )

    import blueprints.plugin as plugin_bp_mod

    monkeypatch.setattr(
        plugin_bp_mod, "handle_request_files", fake_handle_request_files, raising=True
    )

    resp = client.post("/update_now", data={"plugin_id": "image_upload"})
    assert resp.status_code == 500


def test_image_upload_rejects_decode_error(client, monkeypatch):
    # Small bytes with PNG extension but invalid image data
    invalid = b"not-an-image"

    upload = build_upload("bad.png", invalid, "image/png")

    import utils.app_utils as app_utils

    def fake_handle_request_files(request_files, form_data=None):
        if form_data is None:
            form_data = {}
        return app_utils.handle_request_files(
            MultiDict([("imageFiles[]", upload)]), form_data
        )

    import blueprints.plugin as plugin_bp_mod

    monkeypatch.setattr(
        plugin_bp_mod, "handle_request_files", fake_handle_request_files, raising=True
    )

    resp = client.post("/update_now", data={"plugin_id": "image_upload"})
    assert resp.status_code == 500


def test_image_upload_success_returns_sized_image(monkeypatch, device_config_dev):
    # Directly invoke plugin.generate_image to verify contain/pad
    from plugins.image_upload.image_upload import ImageUpload

    buf = BytesIO()
    Image.new("RGB", (1000, 200), "white").save(buf, format="PNG")
    content = buf.getvalue()

    # Save to temp path and feed via settings
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        tf.write(content)
        tf.flush()
        # Upstream only resizes when padImage is true
        img = ImageUpload({"id": "image_upload"}).generate_image(
            {"imageFiles[]": [tf.name], "padImage": "true", "backgroundOption": "blur"},
            device_config_dev,
        )
        assert img is not None
        w, h = device_config_dev.get_resolution()
        # With padImage=true, should be exactly device dimensions
        assert img.size == (w, h)


def test_image_upload_open_image_no_images():
    from plugins.image_upload.image_upload import ImageUpload

    plugin = ImageUpload({"id": "image_upload"})
    with pytest.raises(RuntimeError, match="No images provided"):
        plugin.open_image(0, [])


def test_image_upload_open_image_invalid_file(monkeypatch, tmp_path):
    from PIL import Image

    from plugins.image_upload.image_upload import ImageUpload

    plugin = ImageUpload({"id": "image_upload"})

    # Use a path inside the allowed dir so path validation passes,
    # then mock Image.open to raise an exception
    monkeypatch.setattr(_image_upload_mod, "_get_upload_dir", lambda: str(tmp_path))
    fake_path = str(tmp_path / "missing.png")

    def mock_open(path):
        raise OSError("File not found")

    monkeypatch.setattr(Image, "open", mock_open)

    with pytest.raises(RuntimeError, match="Failed to read image file"):
        plugin.open_image(0, [fake_path])


def test_image_upload_generate_image_index_out_of_range(monkeypatch, device_config_dev):
    import tempfile

    from plugins.image_upload.image_upload import ImageUpload

    plugin = ImageUpload({"id": "image_upload"})

    # Create a test image
    buf = BytesIO()
    Image.new("RGB", (100, 100), "white").save(buf, format="PNG")
    content = buf.getvalue()

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        tf.write(content)
        tf.flush()

        # Test with index out of range - should reset to 0
        result = plugin.generate_image(
            {"imageFiles[]": [tf.name], "image_index": 5}, device_config_dev
        )
        assert result is not None


def test_image_upload_generate_image_randomize(monkeypatch, device_config_dev):
    import tempfile

    from plugins.image_upload.image_upload import ImageUpload

    plugin = ImageUpload({"id": "image_upload"})

    # Create test images
    buf = BytesIO()
    Image.new("RGB", (100, 100), "white").save(buf, format="PNG")
    content = buf.getvalue()

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf1:
        tf1.write(content)
        tf1.flush()

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf2:
        tf2.write(content)
        tf2.flush()

        # Test randomize functionality
        result = plugin.generate_image(
            {"imageFiles[]": [tf1.name, tf2.name], "randomize": "true"},
            device_config_dev,
        )
        assert result is not None


def test_image_upload_generate_image_vertical_orientation(
    monkeypatch, device_config_dev
):
    import tempfile

    from plugins.image_upload.image_upload import ImageUpload

    plugin = ImageUpload({"id": "image_upload"})

    # Mock vertical orientation and resolution
    def mock_get_config(key, default=None):
        if key == "orientation":
            return "vertical"
        elif key == "resolution":
            return (400, 300)  # width, height
        return default

    monkeypatch.setattr(device_config_dev, "get_config", mock_get_config)

    buf = BytesIO()
    Image.new("RGB", (100, 100), "white").save(buf, format="PNG")
    content = buf.getvalue()

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        tf.write(content)
        tf.flush()

        result = plugin.generate_image(
            {"imageFiles[]": [tf.name], "padImage": "false"}, device_config_dev
        )
        assert result is not None


def test_image_upload_missing_background_color(monkeypatch, device_config_dev):
    """Bug 11: Missing backgroundColor should not crash ImageColor.getcolor."""
    import tempfile

    from plugins.image_upload.image_upload import ImageUpload

    plugin = ImageUpload({"id": "image_upload"})

    buf = BytesIO()
    Image.new("RGB", (100, 100), "white").save(buf, format="PNG")
    content = buf.getvalue()

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        tf.write(content)
        tf.flush()

        # padImage=true but no backgroundColor → should use white default
        result = plugin.generate_image(
            {"imageFiles[]": [tf.name], "padImage": "true"}, device_config_dev
        )
        assert result is not None
        w, h = device_config_dev.get_resolution()
        assert result.size == (w, h)


def test_image_upload_generate_image_with_padding(monkeypatch, device_config_dev):
    import tempfile

    from plugins.image_upload.image_upload import ImageUpload

    plugin = ImageUpload({"id": "image_upload"})

    buf = BytesIO()
    Image.new("RGB", (100, 100), "white").save(buf, format="PNG")
    content = buf.getvalue()

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        tf.write(content)
        tf.flush()

        result = plugin.generate_image(
            {
                "imageFiles[]": [tf.name],
                "padImage": "true",
                "backgroundColor": "#FF0000",
            },
            device_config_dev,
        )
        assert result is not None


def test_image_upload_background_option_labels_match_sibling_plugins():
    """JTN-358: Image Upload's Background Fill options must use the same
    labels ('Blur' / 'Color') as Image Folder and Image Album so that all
    three image plugins present a consistent UI. Previously Image Upload
    used 'Solid Color' while the others used 'Color'."""
    from plugins.image_album.image_album import ImageAlbum
    from plugins.image_folder.image_folder import ImageFolder
    from plugins.image_upload.image_upload import ImageUpload

    def _find_background_option_labels(obj):
        """Recursively locate the backgroundOption field and return its
        ordered (value, label) pairs."""
        if isinstance(obj, dict):
            if obj.get("name") == "backgroundOption":
                return [
                    (opt.get("value"), opt.get("label"))
                    for opt in obj.get("options", [])
                ]
            for v in obj.values():
                found = _find_background_option_labels(v)
                if found is not None:
                    return found
        elif isinstance(obj, list):
            for item in obj:
                found = _find_background_option_labels(item)
                if found is not None:
                    return found
        return None

    upload_labels = _find_background_option_labels(
        ImageUpload({"id": "image_upload"}).build_settings_schema()
    )
    folder_labels = _find_background_option_labels(
        ImageFolder({"id": "image_folder"}).build_settings_schema()
    )
    album_labels = _find_background_option_labels(
        ImageAlbum({"id": "image_album"}).build_settings_schema()
    )

    assert upload_labels is not None, "image_upload missing backgroundOption field"
    assert folder_labels is not None, "image_folder missing backgroundOption field"
    assert album_labels is not None, "image_album missing backgroundOption field"

    # Regression guard: 'Solid Color' must not reappear in image_upload.
    upload_label_strings = [label for _value, label in upload_labels]
    assert "Solid Color" not in upload_label_strings, (
        "image_upload should use 'Color' (matching image_folder/image_album), "
        "not 'Solid Color' (JTN-358)"
    )
    assert "Color" in upload_label_strings

    # All three image plugins should expose the same (value, label) pairs.
    assert upload_labels == folder_labels == album_labels, (
        "Background Fill labels must match across image_upload, image_folder, "
        f"and image_album. Got: upload={upload_labels}, folder={folder_labels}, "
        f"album={album_labels}"
    )


def test_image_upload_invalid_background_color_falls_back(
    monkeypatch, device_config_dev
):
    import tempfile

    from plugins.image_upload.image_upload import ImageUpload

    plugin = ImageUpload({"id": "image_upload"})

    buf = BytesIO()
    Image.new("RGB", (100, 100), "white").save(buf, format="PNG")
    content = buf.getvalue()

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        tf.write(content)
        tf.flush()

        result = plugin.generate_image(
            {
                "imageFiles[]": [tf.name],
                "padImage": "true",
                "backgroundOption": "color",
                "backgroundColor": "notacolor",
            },
            device_config_dev,
        )
        assert result is not None


def test_image_upload_background_option_has_default_blur_in_schema():
    """JTN-632: The Background Fill radio_segment must declare a default so
    that DRAFT renders pre-select one option (Blur). Without a default,
    neither radio is checked and users can save in an indeterminate state."""
    from plugins.image_upload.image_upload import ImageUpload

    sch = ImageUpload({"id": "image_upload"}).build_settings_schema()

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
        "image_upload backgroundOption must default to 'blur' so the radio "
        "group has a pre-selected option in DRAFT mode (JTN-632)"
    )


def test_image_upload_draft_page_preselects_blur_radio(client):
    """JTN-632: Rendering /plugin/image_upload with no saved instance
    (DRAFT mode) must pre-check exactly one Background Fill radio option."""
    import re

    resp = client.get("/plugin/image_upload")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")

    # Locate the backgroundOption radio inputs and assert exactly one is checked.
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
    # The pre-checked option must be 'blur' to match generate_image fallback.
    assert re.search(
        r'value="blur"', checked_radios[0]
    ), "the pre-checked backgroundOption radio must be 'blur' (JTN-632)"
