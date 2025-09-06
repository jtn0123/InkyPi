# pyright: reportMissingImports=false
from PIL import Image

from utils.image_utils import apply_image_enhancement, change_orientation


def test_apply_image_enhancement_noop_defaults():
    img = Image.new('RGB', (10, 10), 'gray')
    out = apply_image_enhancement(img, {})
    assert out.size == img.size


def test_change_orientation_inverted_flag():
    img = Image.new('RGB', (20, 10), 'white')
    out = change_orientation(img, 'horizontal', inverted=True)
    # 180-degree rotate keeps size swapped if expand=1, but horizontal keeps angle=180
    assert out.size == (20, 10)

