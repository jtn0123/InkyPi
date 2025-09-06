# pyright: reportMissingImports=false
from PIL import Image
from io import BytesIO


def build_upload(name: str, content: bytes, content_type: str = 'image/png'):
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
            with open(fp, 'wb') as f:
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
    Image.new('RGB', (100, 50), 'white').save(buf, format='PNG')
    content = buf.getvalue()

    data = {
        'plugin_id': 'image_upload',
        'padImage': 'false',
    }

    upload = build_upload('test.png', content, 'image/png')

    # Intercept handle_request_files to feed our upload through the real validator
    import utils.app_utils as app_utils
    def fake_handle_request_files(request_files, form_data={}):
        return app_utils.handle_request_files(MultiDict([('imageFiles[]', upload)]), form_data)

    import blueprints.plugin as plugin_bp_mod
    monkeypatch.setattr(plugin_bp_mod, 'handle_request_files', fake_handle_request_files, raising=True)

    resp = client.post('/update_now', data=data)
    assert resp.status_code == 200


def test_image_upload_rejects_non_image(client, monkeypatch):
    bad_content = b"%PDF-1.4 Not an image"

    upload = build_upload('doc.pdf', bad_content, 'application/pdf')

    import utils.app_utils as app_utils
    def fake_handle_request_files(request_files, form_data={}):
        # Should skip non-allowed extension and thus not crash; return empty map
        return app_utils.handle_request_files(MultiDict([('imageFiles[]', upload)]), form_data)

    import blueprints.plugin as plugin_bp_mod
    monkeypatch.setattr(plugin_bp_mod, 'handle_request_files', fake_handle_request_files, raising=True)

    resp = client.post('/update_now', data={'plugin_id': 'image_upload'})
    # No files processed; plugin will error due to no images provided
    assert resp.status_code == 500


def test_image_upload_rejects_oversize(client, monkeypatch):
    # 11MB fake PNG-like bytes (not decodable)
    big = b"\x89PNG\r\n" + b"0" * (11 * 1024 * 1024)

    upload = build_upload('huge.png', big, 'image/png')

    import os
    monkeypatch.setenv('MAX_UPLOAD_BYTES', str(1024 * 1024))  # 1MB limit

    import utils.app_utils as app_utils
    def fake_handle_request_files(request_files, form_data={}):
        return app_utils.handle_request_files(MultiDict([('imageFiles[]', upload)]), form_data)

    import blueprints.plugin as plugin_bp_mod
    monkeypatch.setattr(plugin_bp_mod, 'handle_request_files', fake_handle_request_files, raising=True)

    resp = client.post('/update_now', data={'plugin_id': 'image_upload'})
    assert resp.status_code == 500


def test_image_upload_rejects_decode_error(client, monkeypatch):
    # Small bytes with PNG extension but invalid image data
    invalid = b"not-an-image"

    upload = build_upload('bad.png', invalid, 'image/png')

    import utils.app_utils as app_utils
    def fake_handle_request_files(request_files, form_data={}):
        return app_utils.handle_request_files(MultiDict([('imageFiles[]', upload)]), form_data)

    import blueprints.plugin as plugin_bp_mod
    monkeypatch.setattr(plugin_bp_mod, 'handle_request_files', fake_handle_request_files, raising=True)

    resp = client.post('/update_now', data={'plugin_id': 'image_upload'})
    assert resp.status_code == 500


def test_image_upload_success_returns_sized_image(monkeypatch, device_config_dev):
    # Directly invoke plugin.generate_image to verify contain/pad
    from plugins.image_upload.image_upload import ImageUpload

    buf = BytesIO()
    Image.new('RGB', (1000, 200), 'white').save(buf, format='PNG')
    content = buf.getvalue()

    # Save to temp path and feed via settings
    import os, tempfile
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tf:
        tf.write(content)
        tf.flush()
        img = ImageUpload({"id": "image_upload"}).generate_image({"imageFiles[]": [tf.name], "padImage": "false"}, device_config_dev)
        assert img is not None
        w, h = device_config_dev.get_resolution()
        assert img.size[0] <= w and img.size[1] <= h


