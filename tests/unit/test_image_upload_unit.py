import random
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

import plugins.image_upload.image_upload as image_upload_mod


class DummyDeviceConfig:
    def __init__(
        self, resolution: Any = (100, 200), orientation: Any = "horizontal"
    ) -> None:
        self._resolution = resolution
        self._orientation = orientation

    def get_resolution(self) -> Any:
        return self._resolution

    def get_config(self, key: Any) -> Any:
        if key == "orientation":
            return self._orientation
        return None


def make_png_file(path: Any, size: Any = (10, 10), color: Any = (255, 0, 0)) -> None:
    img = Image.new("RGB", size, color=color)
    img.save(path, format="PNG")


@pytest.fixture(autouse=True)
def _patch_upload_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point _get_upload_dir to tmp_path so path validation accepts test images."""
    monkeypatch.setattr(image_upload_mod, "_get_upload_dir", lambda: str(tmp_path))


def test_open_image_success(tmp_path: Path) -> None:
    p = tmp_path / "img.png"
    make_png_file(p)
    u = image_upload_mod.ImageUpload({"id": "image_upload"})
    img = u.open_image(0, [str(p)])
    assert isinstance(img, Image.Image)


def _save_jpeg(path: Path, size: tuple[int, int], orientation: int = 1) -> None:
    exif = Image.Exif()
    exif[0x0112] = orientation
    Image.new("RGB", size, (0, 0, 255)).save(path, "JPEG", exif=exif.tobytes())


def test_open_image_applies_exif_orientation(tmp_path: Path) -> None:
    # Uploads are stored as received, so the plugin must turn the photo upright.
    p = tmp_path / "phone.jpg"
    _save_jpeg(p, (40, 20), orientation=6)
    u = image_upload_mod.ImageUpload({"id": "image_upload"})
    img = u.open_image(0, [str(p)])
    assert img.size == (20, 40)


def test_open_image_size_hint_decodes_big_jpeg_smaller(tmp_path: Path) -> None:
    p = tmp_path / "big.jpg"
    _save_jpeg(p, (4000, 3000), orientation=6)
    u = image_upload_mod.ImageUpload({"id": "image_upload"})
    img = u.open_image(0, [str(p)], size_hint=(800, 480))
    # Decoded at half scale, not 4000x3000, and still covers the panel's
    # larger side in both directions after the EXIF rotation.
    assert img.size == (1500, 2000)


def test_generate_image_shows_a_rotated_upload_upright(tmp_path: Path) -> None:
    # A portrait photo (stored landscape plus EXIF 6) on a portrait panel
    # fills it with no padding, as it would if it were stored upright.
    p = tmp_path / "portrait.jpg"
    _save_jpeg(p, (200, 100), orientation=6)
    u = image_upload_mod.ImageUpload({"id": "image_upload"})
    img = u.generate_image(
        {"imageFiles[]": [str(p)], "fitMode": "contain", "backgroundColor": "#ff0000"},
        DummyDeviceConfig(resolution=(100, 200)),
    )
    assert img.size == (100, 200)
    assert img.getpixel((50, 2))[:3] != (255, 0, 0)


def test_open_image_no_images() -> None:
    u = image_upload_mod.ImageUpload({"id": "image_upload"})
    with pytest.raises(RuntimeError):
        u.open_image(0, [])


def test_open_image_bad_path(tmp_path: Path) -> None:
    u = image_upload_mod.ImageUpload({"id": "image_upload"})
    # Path inside tmp_path (allowed dir) but does not exist — triggers OSError in Image.open
    bad = str(tmp_path / "nonexistent.png")
    with pytest.raises(RuntimeError):
        u.open_image(0, [bad])


def test_generate_image_no_images() -> None:
    u = image_upload_mod.ImageUpload({"id": "image_upload"})
    settings: dict = {}
    with pytest.raises(RuntimeError):
        u.generate_image(settings, DummyDeviceConfig())


def test_generate_image_index_wrap_and_increment(tmp_path: Path) -> None:
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


def test_generate_image_randomize(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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


def test_generate_image_padImage_true(tmp_path: Path) -> None:
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


def test_open_image_rejects_path_traversal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """open_image must reject paths that escape the upload directory."""
    # _get_upload_dir is already patched to tmp_path by autouse fixture
    u = image_upload_mod.ImageUpload({"id": "image_upload"})
    malicious = str(tmp_path / ".." / ".." / "etc" / "passwd")
    with pytest.raises(RuntimeError, match="Invalid image file path"):
        u.open_image(0, [malicious])


def test_open_image_rejects_absolute_outside(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """open_image must reject absolute paths outside the upload directory."""
    u = image_upload_mod.ImageUpload({"id": "image_upload"})
    with pytest.raises(RuntimeError, match="Invalid image file path"):
        u.open_image(0, ["/etc/passwd"])


def test_cleanup_skips_invalid_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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


def test_cleanup_skips_traversal_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """cleanup must skip traversal paths without raising."""
    settings = {
        "imageFiles[]": [str(tmp_path / ".." / ".." / "etc" / "passwd")],
    }
    u = image_upload_mod.ImageUpload({"id": "image_upload"})
    # Must not raise
    u.cleanup(settings)
