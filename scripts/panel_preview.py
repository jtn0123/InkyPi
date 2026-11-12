#!/usr/bin/env python3
"""Approximate how an image looks on a Spectra 6 Inky Impression panel.

Writes a side-by-side sheet: original | current (dithered) | crisp.

* "current" reproduces what the inky driver does with an ordinary RGB frame:
  Floyd-Steinberg error diffusion against a 50/50 blend of pure primaries and
  Pimoroni's measured panel colours (``saturation=0.5``).
* "crisp" is InkyPi's undithered conversion for rendered dashboards
  (``display.crisp``), used when a plugin declares ``"crisp"`` in its
  ``image_settings``.

Both are drawn with the panel colours Pimoroni measured for the driver
(``SATURATED_PALETTE`` in ``inky.inky_e673``), brightened so panel white
reads as paper white. That is an approximation for judging layouts and
colour choices, not a calibrated model of the panel: real ink varies with
temperature, viewing light and the individual display.

Usage (from the repo root):
  python scripts/panel_preview.py weather.png
  python scripts/panel_preview.py weather.png --output /tmp/weather_sheet.png
  python scripts/dry_run_plugin.py --plugin clock --output /tmp/c.png && \\
      python scripts/panel_preview.py /tmp/c.png
"""

from __future__ import annotations

import argparse
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageOps

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(REPO_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from display.crisp import crisp_indices  # noqa: E402

# Spectra 6 colour order used by inky.inky_e673: black, white, yellow, red,
# blue, green. IDEAL is the driver's DESATURATED_PALETTE, MEASURED its
# SATURATED_PALETTE (Pimoroni's photographed panel colours).
IDEAL = np.array(
    [[0, 0, 0], [255, 255, 255], [255, 255, 0], [255, 0, 0], [0, 0, 255], [0, 255, 0]],
    dtype=float,
)
MEASURED = np.array(
    [
        [0, 0, 0],
        [161, 164, 165],
        [208, 190, 71],
        [156, 72, 75],
        [61, 59, 94],
        [58, 91, 70],
    ],
    dtype=float,
)
PANEL_SIZE = (800, 480)
GUTTER = 20
LABEL_HEIGHT = 24


def _palette_image(colours: np.ndarray) -> Image.Image:
    pal = Image.new("P", (1, 1))
    pal.putpalette(np.clip(colours, 0, 255).astype(np.uint8).flatten().tobytes())
    return pal


def render_on_panel(indices: np.ndarray) -> Image.Image:
    """Draw palette indexes with the measured colours, white-normalised."""
    lut = np.clip(MEASURED * (240.0 / MEASURED[1].max()), 0, 255).astype(np.uint8)
    return Image.fromarray(lut[indices], "RGB")


def _blend(saturation: float) -> np.ndarray:
    """The driver's ``_palette_blend``: what it error-diffuses against."""
    return (IDEAL * (1 - saturation) + MEASURED * saturation).astype(int)


def current(image: Image.Image, saturation: float = 0.5) -> np.ndarray:
    """Palette indexes the inky driver produces for an RGB frame today."""
    quantized = image.convert("RGB").quantize(
        len(IDEAL),
        palette=_palette_image(_blend(saturation)),
        dither=Image.Dither.FLOYDSTEINBERG,
    )
    return np.asarray(quantized, dtype=np.uint8)


def crisp(image: Image.Image, saturation: float = 0.5) -> np.ndarray:
    """Palette indexes from InkyPi's crisp conversion."""
    return crisp_indices(image, IDEAL.astype(int).tolist(), _blend(saturation).tolist())


def build_sheet(image: Image.Image) -> Image.Image:
    img = ImageOps.fit(image.convert("RGB"), PANEL_SIZE, Image.Resampling.LANCZOS)
    panels = [
        ("original", img),
        ("current (dithered)", render_on_panel(current(img))),
        ("crisp", render_on_panel(crisp(img))),
    ]
    width = PANEL_SIZE[0] * len(panels) + GUTTER * (len(panels) - 1)
    sheet = Image.new("RGB", (width, PANEL_SIZE[1] + LABEL_HEIGHT), "white")
    draw = ImageDraw.Draw(sheet)
    for i, (label, panel) in enumerate(panels):
        x = i * (PANEL_SIZE[0] + GUTTER)
        draw.text((x + 4, 6), label, fill="black")
        sheet.paste(panel, (x, LABEL_HEIGHT))
    return sheet


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("image", help="input image (fitted to 800x480)")
    parser.add_argument(
        "--output", help="output sheet path (default: <input>_sheet.png)"
    )
    args = parser.parse_args(argv)
    output = args.output or os.path.splitext(args.image)[0] + "_sheet.png"
    with Image.open(args.image) as src:
        build_sheet(src).save(output)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
