"""Crisp (undithered) conversion of rendered UI for colour e-ink panels."""

from __future__ import annotations

import importlib.util
import json
import re
import time
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from display import crisp
from display.crisp import crisp_image, crisp_indices, photo_regions

REPO_ROOT = Path(__file__).resolve().parents[2]

# Spectra 6 order used by inky.inky_e673: black, white, yellow, red, blue, green.
SPECTRA6 = [
    (0, 0, 0),
    (255, 255, 255),
    (255, 255, 0),
    (255, 0, 0),
    (0, 0, 255),
    (0, 255, 0),
]
BLEND = [
    (0, 0, 0),
    (208, 209, 210),
    (231, 222, 163),
    (205, 36, 37),
    (30, 29, 174),
    (29, 173, 35),
]
BLACK, WHITE, YELLOW, RED, BLUE, GREEN = range(6)
FOUR_COLOUR = SPECTRA6[:4]


def _dashboard() -> Image.Image:
    """A small synthetic dashboard: text, thin lines, a pale icon, a chart."""
    img = Image.new("RGB", (800, 480), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle((20, 20, 220, 30), fill=(0, 0, 0))  # heading bar
    draw.rectangle((20, 40, 220, 46), fill=(102, 102, 102))  # secondary text grey
    draw.line((20, 60, 780, 60), fill=(170, 170, 170), width=1)  # #AAA divider
    draw.ellipse((300, 100, 380, 180), fill=(144, 202, 249))  # light-blue icon
    draw.rectangle((420, 100, 500, 180), fill=(255, 196, 0))  # amber sun
    draw.rectangle((520, 100, 600, 180), fill=(208, 88, 88))  # muted red
    draw.rectangle((620, 100, 700, 180), fill=(19, 247, 2))  # vivid green
    draw.rectangle((20, 300, 780, 460), fill=(250, 250, 250))  # near-white card
    draw.line((20, 400, 780, 380), fill=(0, 0, 0), width=1)  # thin black line
    return img


def _photo(size: tuple[int, int], seed: int = 0) -> Image.Image:
    rng = np.random.default_rng(seed)
    noise = rng.integers(0, 256, size=(size[1], size[0], 3), dtype=np.uint8)
    return Image.fromarray(noise, "RGB")


def _isolated_pixels(indices: np.ndarray) -> int:
    """Pixels that differ from all four neighbours (dither speckle)."""
    core = indices[1:-1, 1:-1]
    return int(
        (
            (core != indices[:-2, 1:-1])
            & (core != indices[2:, 1:-1])
            & (core != indices[1:-1, :-2])
            & (core != indices[1:-1, 2:])
        ).sum()
    )


def test_output_uses_only_palette_colours() -> None:
    out = crisp_image(_dashboard(), SPECTRA6, BLEND)
    colours = {c for _n, c in out.getcolors(16) or []}
    assert colours <= set(SPECTRA6)


def test_flat_areas_have_no_speckle() -> None:
    idx = crisp_indices(_dashboard(), SPECTRA6, BLEND)
    assert _isolated_pixels(idx) == 0


def test_text_and_thin_lines_stay_black() -> None:
    idx = crisp_indices(_dashboard(), SPECTRA6, BLEND)
    assert (idx[20:31, 20:221] == BLACK).all()
    assert (idx[40:47, 20:221] == BLACK).all()  # secondary grey text
    assert (idx[60, 20:781] == BLACK).all()  # light divider survives
    line = idx[380:401, 400]
    assert (line == BLACK).any()


def test_near_white_stays_white() -> None:
    idx = crisp_indices(_dashboard(), SPECTRA6, BLEND)
    assert (idx[310:370, 30:770] == WHITE).all()
    assert (idx[200:290, 30:770] == WHITE).all()


def test_saturated_light_blue_icon_becomes_solid_blue() -> None:
    idx = crisp_indices(_dashboard(), SPECTRA6, BLEND)
    assert (idx[120:160, 320:360] == BLUE).all()


def test_colours_snap_to_nearest_panel_hue() -> None:
    idx = crisp_indices(_dashboard(), SPECTRA6, BLEND)
    assert (idx[110:170, 430:490] == YELLOW).all()  # amber
    assert (idx[110:170, 530:590] == RED).all()  # owner's #d05858 background
    assert (idx[110:170, 630:690] == GREEN).all()  # owner's #13f702


def test_unmatched_hue_falls_back_to_neutral_rule() -> None:
    """Blue on a black/white/yellow/red panel is ink, not a wrong colour."""
    img = Image.new("RGB", (64, 64), "white")
    ImageDraw.Draw(img).rectangle((10, 10, 50, 50), fill=(20, 40, 160))
    idx = crisp_indices(img, FOUR_COLOUR)
    assert (idx[15:45, 15:45] == BLACK).all()
    assert idx[0, 0] == WHITE


def test_dark_paper_makes_light_content_white() -> None:
    img = Image.new("RGB", (64, 64), "black")
    ImageDraw.Draw(img).rectangle((10, 10, 50, 30), fill=(170, 170, 170))
    ImageDraw.Draw(img).rectangle((10, 40, 50, 50), fill=(40, 40, 40))
    idx = crisp_indices(img, SPECTRA6)
    assert (idx[12:28, 12:48] == WHITE).all()
    assert (idx[42:48, 12:48] == BLACK).all()  # dim, close to the paper
    assert idx[0, 0] == BLACK


def test_monochrome_palette_has_no_colour_path() -> None:
    img = Image.new("RGB", (32, 32), (255, 0, 0))
    idx = crisp_indices(img, [(0, 0, 0), (255, 255, 255)])
    assert set(np.unique(idx)) <= {0, 1}


def test_embedded_photo_is_dithered_and_ui_is_not() -> None:
    img = _dashboard()
    img.paste(_photo((160, 96)), (600, 320))
    regions = photo_regions(
        (np.asarray(img, dtype=np.int32) * [65536, 256, 1]).sum(axis=2)
    )
    assert len(regions) == 1
    left, top, right, bottom = regions[0]
    assert left <= 600 and top <= 320 and right >= 760 and bottom >= 416

    idx = crisp_indices(img, SPECTRA6, BLEND)
    photo_part = idx[330:400, 610:750]
    expected = np.asarray(
        img.crop(regions[0]).quantize(
            6, palette=_palette_image(BLEND), dither=Image.Dither.FLOYDSTEINBERG
        )
    )
    np.testing.assert_array_equal(idx[top:bottom, left:right], expected)
    assert len(np.unique(photo_part)) > 3
    # The rest of the frame is still crisp.
    assert (idx[120:160, 320:360] == BLUE).all()


def test_small_busy_patches_are_not_photos() -> None:
    img = Image.new("RGB", (200, 200), "white")
    img.paste(_photo((16, 16)), (50, 50))
    img.paste(_photo((24, 24), seed=3), (128, 128))  # a few cores, too few
    packed = (np.asarray(img, dtype=np.int32) * [65536, 256, 1]).sum(axis=2)
    assert photo_regions(packed) == []
    assert photo_regions(packed[:4, :4]) == []


def _gradient_face(size: tuple[int, int] = (800, 480)) -> Image.Image:
    """A full-frame red/black gradient with a clock hand, like the gradient face."""
    w, h = size
    ys, xs = np.mgrid[0:h, 0:w]
    rgb = np.zeros((h, w, 3), dtype=np.uint8)
    rgb[..., 0] = (255 * xs / w).astype(np.uint8)
    rgb[..., 2] = (120 * ys / h).astype(np.uint8)
    img = Image.fromarray(rgb, "RGB")
    ImageDraw.Draw(img).line((400, 240, 600, 260), fill="white", width=8)  # hand
    return img


def test_gradient_dominated_frame_is_detected() -> None:
    assert crisp.gradient_dominated(_gradient_face())


def test_dashboard_with_small_gradient_stays_crisp() -> None:
    img = _dashboard()
    # A decorative vertical gradient (a sun or chart fill), ~5% of the frame.
    ramp = np.linspace(180, 255, 120).astype(np.uint8)
    fill = np.zeros((120, 160, 3), dtype=np.uint8)
    fill[..., 0] = 255
    fill[..., 1] = ramp[:, None]
    img.paste(Image.fromarray(fill, "RGB"), (40, 200))
    assert not crisp.gradient_dominated(img)

    idx = crisp_indices(img, SPECTRA6, BLEND)
    assert (idx[205:315, 45:195] == YELLOW).all()  # flattened, no speckle
    assert (idx[120:160, 320:360] == BLUE).all()
    # Text with anti-aliasing is not gradient either.
    assert not crisp.gradient_dominated(_dashboard())
    assert not crisp.gradient_dominated(Image.new("RGB", (4, 4)))


def test_dither_palette_defaults_to_pure_palette() -> None:
    img = _photo((96, 96))
    idx = crisp_indices(img, SPECTRA6)
    assert set(np.unique(idx)) <= set(range(6))


def test_converts_non_rgb_input() -> None:
    img = Image.new("RGBA", (40, 40), (0, 0, 255, 255))
    assert (crisp_indices(img, SPECTRA6) == BLUE).all()


def test_full_frame_is_fast() -> None:
    img = _dashboard()
    img.paste(_photo((200, 120)), (560, 320))
    crisp_indices(img, SPECTRA6, BLEND)
    start = time.perf_counter()
    crisp_indices(img, SPECTRA6, BLEND)
    # Tens of milliseconds on a desktop; generous for slow CI runners.
    assert time.perf_counter() - start < 2.0


def _palette_image(colours: list[tuple[int, int, int]]) -> Image.Image:
    pal = Image.new("P", (1, 1))
    pal.putpalette(bytes(v for c in colours for v in c))
    return pal


def test_render_image_plugins_declare_crisp() -> None:
    """Every plugin that renders HTML (or draws UI, like clock) opts in."""
    plugins_dir = REPO_ROOT / "src" / "plugins"
    declared = set()
    renders_html = set()
    for info_path in plugins_dir.glob("*/plugin-info.json"):
        info = json.loads(info_path.read_text(encoding="utf-8"))
        if crisp.CRISP_IMAGE_SETTING in info.get("image_settings", []):
            declared.add(info["id"])
        source = "\n".join(
            p.read_text(encoding="utf-8") for p in info_path.parent.glob("*.py")
        )
        if re.search(r"\.render_image\(", source):
            renders_html.add(info["id"])
    assert renders_html, "expected HTML-rendering plugins"
    assert renders_html <= declared
    assert "clock" in declared
    photo_plugins = {
        "wpotd",
        "apod",
        "image_upload",
        "image_url",
        "image_folder",
        "unsplash",
    }
    assert not (declared & photo_plugins)


def test_panel_preview_script_builds_sheet(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location(
        "panel_preview", REPO_ROOT / "scripts" / "panel_preview.py"
    )
    assert spec is not None and spec.loader is not None
    module: Any = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    src = tmp_path / "frame.png"
    _dashboard().save(src)
    assert module.main([str(src)]) == 0
    sheet = Image.open(tmp_path / "frame_sheet.png")
    assert sheet.width == 800 * 3 + 2 * module.GUTTER
