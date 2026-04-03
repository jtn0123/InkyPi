import random

import pytest
from PIL import Image

import plugins.image_upload.image_upload as image_upload_mod


class DummyDeviceConfig:
    def __init__(self, resolution=(100, 200), orientation="horizontal"):
        self._resolution = resolution
        self._orientation = orientation

    def get_resolution(self):
        return self._resolution

    def get_config(self, key):
        if key == "orientation":
            return self._orientation
        return None


def make_png_file(path, size=(10, 10), color=(255, 0, 0)):
    img = Image.new("RGB", size, color=color)
    img.save(path, format="PNG")


@pytest.fixture(autouse=True)
def _patch_upload_dir(tmp_path, monkeypatch):
    """Point _get_upload_dir to tmp_path so path validation accepts test images."""
    monkeypatch.setattr(image_upload_mod, "_get_upload_dir", lambda: str(tmp_path))


def test_open_image_success(tmp_path):
    p = tmp_path / "img.png"
    make_png_file(p)
    u = image_upload_mod.ImageUpload({"id": "image_upload"})
    img = u.open_image(0, [str(p)])
    assert isinstance(img, Image.Image)


def test_open_image_no_images():
    u = image_upload_mod.ImageUpload({"id": "image_upload"})
    with pytest.raises(RuntimeError):
        u.open_image(0, [])


def test_open_image_bad_path(tmp_path):
    u = image_upload_mod.ImageUpload({"id": "image_upload"})
    # Path inside tmp_path (allowed dir) but does not exist — triggers OSError in Image.open
    bad = str(tmp_path / "nonexistent.png")
    with pytest.raises(RuntimeError):
        u.open_image(0, [bad])


def test_generate_image_no_images():
    u = image_upload_mod.ImageUpload({"id": "image_upload"})
    settings: dict = {}
    with pytest.raises(RuntimeError):
        u.generate_image(settings, DummyDeviceConfig())


def test_generate_image_index_wrap_and_increment(tmp_path):
    # create two images
    p1 = tmp_path / "a.png"
    p2 = tmp_path / "b.png"
    make_png_file(p1, size=(50, 50))
    make_png_file(p2, size=(20, 40))

    settings = {"image_index": 5, "imageFiles[]": [str(p1), str(p2)]}
    u = image_upload_mod.ImageUpload({"id": "image_upload"})
    out = u.generate_image(settings, DummyDeviceConfig(resolution=(30, 30)))
    # image_index should have been reset to 0 then incremented to 1
    assert settings["image_index"] == 1
    assert isinstance(out, Image.Image)


def test_generate_image_randomize(monkeypatch, tmp_path):
    p1 = tmp_path / "a.png"
    p2 = tmp_path / "b.png"
    make_png_file(p1, size=(10, 10))
    make_png_file(p2, size=(20, 20))

    settings = {
        "image_index": 0,
        "imageFiles[]": [str(p1), str(p2)],
        "randomize": "true",
    }
    # force random.randrange to pick index 1
    monkeypatch.setattr(random, "randrange", lambda a, b: 1)
    u = image_upload_mod.ImageUpload({"id": "image_upload"})
    out = u.generate_image(settings, DummyDeviceConfig(resolution=(15, 15)))
    assert isinstance(out, Image.Image)


def test_generate_image_padImage_true(tmp_path):
    p = tmp_path / "wide.png"
    # wide image
    make_png_file(p, size=(200, 50))

    settings = {
        "image_index": 0,
        "imageFiles[]": [str(p)],
        "padImage": "true",
        "backgroundColor": "rgb(255,255,255)",
    }
    u = image_upload_mod.ImageUpload({"id": "image_upload"})
    device = DummyDeviceConfig(resolution=(100, 200))
    out = u.generate_image(settings, device)
    # When padding, upstream uses ImageOps.pad() which pads to exact device dimensions
    assert out.size == device.get_resolution()


# ---------------------------------------------------------------------------
# Path traversal / security tests
# ---------------------------------------------------------------------------


def test_open_image_rejects_path_traversal(tmp_path, monkeypatch):
    """open_image must reject paths that escape the upload directory."""
    # _get_upload_dir is already patched to tmp_path by autouse fixture
    u = image_upload_mod.ImageUpload({"id": "image_upload"})
    malicious = str(tmp_path / ".." / ".." / "etc" / "passwd")
    with pytest.raises(RuntimeError, match="Invalid image file path"):
        u.open_image(0, [malicious])


def test_open_image_rejects_absolute_outside(tmp_path, monkeypatch):
    """open_image must reject absolute paths outside the upload directory."""
    u = image_upload_mod.ImageUpload({"id": "image_upload"})
    with pytest.raises(RuntimeError, match="Invalid image file path"):
        u.open_image(0, ["/etc/passwd"])


def test_cleanup_skips_invalid_paths(tmp_path, monkeypatch):
    """cleanup must silently skip paths outside the upload directory."""
    # Create a file inside the allowed dir to verify it gets cleaned up
    safe_file = tmp_path / "safe.png"
    make_png_file(safe_file)

    settings = {
        "imageFiles[]": ["/etc/passwd", str(safe_file)],
    }
    u = image_upload_mod.ImageUpload({"id": "image_upload"})
    # Should not raise — the invalid path is skipped, the safe path is deleted
    u.cleanup(settings)
    assert not safe_file.exists(), "Safe file should have been deleted"


def test_cleanup_skips_traversal_paths(tmp_path, monkeypatch):
    """cleanup must skip traversal paths without raising."""
    settings = {
        "imageFiles[]": [str(tmp_path / ".." / ".." / "etc" / "passwd")],
    }
    u = image_upload_mod.ImageUpload({"id": "image_upload"})
    # Must not raise
    u.cleanup(settings)
