# pyright: reportMissingImports=false
"""Tests for utils/image_utils.py — remaining coverage gaps."""
from PIL import Image


def test_compute_image_hash_consistency():
    from utils.image_utils import compute_image_hash

    img = Image.new("RGB", (100, 100), "red")
    h1 = compute_image_hash(img)
    h2 = compute_image_hash(img)
    assert h1 == h2


def test_compute_image_hash_different():
    from utils.image_utils import compute_image_hash

    img1 = Image.new("RGB", (100, 100), "red")
    img2 = Image.new("RGB", (100, 100), "blue")
    assert compute_image_hash(img1) != compute_image_hash(img2)


def test_pad_image_blur():
    from utils.image_utils import pad_image_blur

    # Narrow image padded to wider dimensions
    img = Image.new("RGB", (100, 200), "green")
    result = pad_image_blur(img, (400, 300))
    assert result.size == (400, 300)
