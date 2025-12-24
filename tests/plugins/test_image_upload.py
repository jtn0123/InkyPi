# pyright: reportMissingImports=false
from io import BytesIO

from PIL import Image
import pytest

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

    def fake_handle_request_files(request_files, form_data={}):
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

    def fake_handle_request_files(request_files, form_data={}):
        # Should skip non-allowed extension and thus not crash; return empty map
        return app_utils.handle_request_files(
            MultiDict([("imageFiles[]", upload)]), form_data
        )

    import blueprints.plugin as plugin_bp_mod

    monkeypatch.setattr(
        plugin_bp_mod, "handle_request_files", fake_handle_request_files, raising=True
    )

    resp = client.post("/update_now", data={"plugin_id": "image_upload"})
    # No files processed; plugin will error due to no images provided
    assert resp.status_code == 500

def test_image_upload_rejects_oversize(client, monkeypatch):
    # 11MB fake PNG-like bytes (not decodable)
    big = b"\x89PNG\r\n" + b"0" * (11 * 1024 * 1024)

    upload = build_upload("huge.png", big, "image/png")

    monkeypatch.setenv("MAX_UPLOAD_BYTES", str(1024 * 1024))  # 1MB limit

    import utils.app_utils as app_utils

    def fake_handle_request_files(request_files, form_data={}):
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

    def fake_handle_request_files(request_files, form_data={}):
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
            {"imageFiles[]": [tf.name], "padImage": "true", "backgroundOption": "blur"}, device_config_dev
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

def test_image_upload_open_image_invalid_file(monkeypatch):
    from plugins.image_upload.image_upload import ImageUpload
    from PIL import Image

    plugin = ImageUpload({"id": "image_upload"})

    # Mock Image.open to raise exception (upstream uses Image.open directly)
    def mock_open(path):
        raise IOError("File not found")

    monkeypatch.setattr(Image, "open", mock_open)

    with pytest.raises(RuntimeError, match="Failed to read image file"):
        plugin.open_image(0, ["/fake/path.png"])

def test_image_upload_generate_image_index_out_of_range(monkeypatch, device_config_dev):
    from plugins.image_upload.image_upload import ImageUpload
    import tempfile

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
    from plugins.image_upload.image_upload import ImageUpload
    import tempfile

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
            {"imageFiles[]": [tf1.name, tf2.name], "randomize": "true"}, device_config_dev
        )
        assert result is not None

def test_image_upload_generate_image_vertical_orientation(monkeypatch, device_config_dev):
    from plugins.image_upload.image_upload import ImageUpload
    import tempfile

    plugin = ImageUpload({"id": "image_upload"})

    # Mock vertical orientation and resolution
    def mock_get_config(key):
        if key == "orientation":
            return "vertical"
        elif key == "resolution":
            return (400, 300)  # width, height
        return None

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

def test_image_upload_generate_image_with_padding(monkeypatch, device_config_dev):
    from plugins.image_upload.image_upload import ImageUpload
    import tempfile

    plugin = ImageUpload({"id": "image_upload"})

    buf = BytesIO()
    Image.new("RGB", (100, 100), "white").save(buf, format="PNG")
    content = buf.getvalue()

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        tf.write(content)
        tf.flush()

        result = plugin.generate_image(
            {"imageFiles[]": [tf.name], "padImage": "true", "backgroundColor": "#FF0000"}, device_config_dev
        )
        assert result is not None
