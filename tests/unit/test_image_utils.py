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


