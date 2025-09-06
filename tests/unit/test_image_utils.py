from io import BytesIO

import pytest
from PIL import Image

import utils.image_utils as image_utils


class FakeResp:
    def __init__(self, content, status_code=200):
        self.content = content
        self.status_code = status_code

    def raise_for_status(self):
        if not (200 <= self.status_code < 300 or self.status_code == 304):
            raise Exception("HTTP error")


def make_png_bytes(size=(10, 10), color=(1, 2, 3)):
    bio = BytesIO()
    Image.new('RGB', size, color=color).save(bio, format='PNG')
    return bio.getvalue()


def test_get_image_success(monkeypatch):
    content = make_png_bytes()

    def fake_get(url, timeout=None):
        return FakeResp(content, 200)

    monkeypatch.setattr(image_utils, 'requests', type('R', (), {'get': staticmethod(fake_get)}))
    img = image_utils.get_image('http://example.com/img.png')
    assert isinstance(img, Image.Image)


def test_get_image_typeerror_fallback(monkeypatch):
    content = make_png_bytes()

    def fake_get(url, timeout=None):
        if timeout is not None:
            raise TypeError("no timeout support")
        return FakeResp(content, 200)

    monkeypatch.setattr(image_utils, 'requests', type('R', (), {'get': staticmethod(fake_get)}))
    img = image_utils.get_image('http://example.com/img.png')
    assert isinstance(img, Image.Image)


def test_get_image_non200(monkeypatch):
    def fake_get(url, timeout=None):
        return FakeResp(b'', 404)

    monkeypatch.setattr(image_utils, 'requests', type('R', (), {'get': staticmethod(fake_get)}))
    assert image_utils.get_image('http://example.com/notfound') is None


def test_change_orientation():
    img = Image.new('RGB', (30, 10), 'white')
    out_h = image_utils.change_orientation(img, 'horizontal')
    assert out_h.size != ()
    out_v = image_utils.change_orientation(img, 'vertical')
    # vertical should change orientation (width/height swap when expanded)
    assert out_v.size[0] != img.size[0] or out_v.size[1] != img.size[1]


def test_resize_image_and_keep_width():
    img = Image.new('RGB', (200, 100), 'white')
    out = image_utils.resize_image(img, (100, 100))
    assert out.size == (100, 100)

    out2 = image_utils.resize_image(img, (100, 100), image_settings=['keep-width'])
    assert out2.size == (100, 100)


def test_apply_image_enhancement_and_compute_hash():
    img = Image.new('RGB', (10, 10), 'white')
    enhanced = image_utils.apply_image_enhancement(img, {'brightness': 1.2, 'contrast': 0.9, 'saturation': 1.0, 'sharpness': 1.0})
    assert isinstance(enhanced, Image.Image)
    h = image_utils.compute_image_hash(enhanced)
    assert isinstance(h, str) and len(h) == 64

    with pytest.raises(ValueError):
        image_utils.compute_image_hash(None)


def test_take_screenshot_html(tmp_path):
    # conftest patches take_screenshot to a fake in-memory generator
    html = '<html><body>test</body></html>'
    dims = (80, 60)
    img = image_utils.take_screenshot_html(html, dims)
    assert isinstance(img, Image.Image)
    assert img.size == dims

# pyright: reportMissingImports=false
from PIL import Image

from utils.image_utils import change_orientation, resize_image, compute_image_hash


def test_change_orientation_vertical():
    img = Image.new('RGB', (100, 50), 'white')
    out = change_orientation(img, 'vertical')
    assert out.size == (50, 100)


def test_resize_image_aspect_crop():
    img = Image.new('RGB', (160, 100), 'white')
    out = resize_image(img, (80, 80), [])
    assert out.size == (80, 80)


def test_compute_image_hash_deterministic():
    img1 = Image.new('RGB', (10, 10), 'white')
    img2 = Image.new('RGB', (10, 10), 'white')
    assert compute_image_hash(img1) == compute_image_hash(img2)


