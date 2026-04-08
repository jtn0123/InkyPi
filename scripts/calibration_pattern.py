#!/usr/bin/env python3
"""
Generate e-ink display calibration test patterns.

Usage:
    python scripts/calibration_pattern.py --width 800 --height 480
    python scripts/calibration_pattern.py --profile grayscale --output-dir /tmp/cal
    python scripts/calibration_pattern.py --profile mono --width 400 --height 300

Outputs a set of PNG images useful for tuning e-ink displays:
  01_pure_colors.png      — solid color blocks in a 4x2 grid
  02_grayscale_ramp.png   — 16-step horizontal ramp
  03_dithering_grid.png   — 25%/50%/75% gray with dithering comparison
  04_font_resolution.png  — text at 8/10/12/14/18/24/32 pt
  05_edge_sharpness.png   — diagonal edges, concentric circles, Siemens star
  06_full_refresh.png     — alternating single-pixel columns for ghosting detection
"""

from __future__ import annotations

import argparse
import math
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# Pattern generators
# ---------------------------------------------------------------------------


def make_pure_colors(w: int, h: int) -> Image.Image:
    """4x2 grid of pure R, G, B, Black, White, Cyan, Magenta, Yellow with labels."""
    img = Image.new("RGB", (w, h), "white")
    draw = ImageDraw.Draw(img)

    colors = [
        ("Red", (255, 0, 0)),
        ("Green", (0, 255, 0)),
        ("Blue", (0, 0, 255)),
        ("Black", (0, 0, 0)),
        ("White", (255, 255, 255)),
        ("Cyan", (0, 255, 255)),
        ("Magenta", (255, 0, 255)),
        ("Yellow", (255, 255, 0)),
    ]

    cols, rows = 4, 2
    cell_w = w // cols
    cell_h = h // rows

    font = _default_font(14)

    for idx, (label, color) in enumerate(colors):
        col = idx % cols
        row = idx // cols
        x0, y0 = col * cell_w, row * cell_h
        x1, y1 = x0 + cell_w, y0 + cell_h
        draw.rectangle([x0, y0, x1, y1], fill=color)

        # Choose contrasting text color
        luma = 0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2]
        text_color = "black" if luma > 128 else "white"
        # Center label
        try:
            bbox = draw.textbbox((0, 0), label, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
        except AttributeError:
            tw, th = draw.textsize(label, font=font)  # type: ignore[attr-defined]
        tx = x0 + (cell_w - tw) // 2
        ty = y0 + (cell_h - th) // 2
        draw.text((tx, ty), label, fill=text_color, font=font)

    return img


def make_grayscale_ramp(w: int, h: int) -> Image.Image:
    """Horizontal ramp from black to white in 16 evenly spaced steps."""
    img = Image.new("RGB", (w, h), "white")
    draw = ImageDraw.Draw(img)

    steps = 16
    step_w = w // steps
    font = _default_font(11)

    for i in range(steps):
        v = int(round(i * 255 / (steps - 1)))
        color = (v, v, v)
        x0 = i * step_w
        x1 = x0 + step_w if i < steps - 1 else w
        draw.rectangle([x0, 0, x1, h], fill=color)

        # Label each step with its value
        label = str(v)
        text_color = "white" if v < 128 else "black"
        try:
            bbox = draw.textbbox((0, 0), label, font=font)
            tw = bbox[2] - bbox[0]
        except AttributeError:
            tw, _ = draw.textsize(label, font=font)  # type: ignore[attr-defined]
        tx = x0 + (step_w - tw) // 2
        ty = h // 2 - 8
        draw.text((tx, ty), label, fill=text_color, font=font)

    return img


def make_dithering_grid(w: int, h: int) -> Image.Image:
    """Three areas showing 25%/50%/75% gray with dithering comparison."""
    img = Image.new("RGB", (w, h), "white")
    draw = ImageDraw.Draw(img)
    font = _default_font(12)

    # Three gray levels in the top half; dithered 1-bit versions in the bottom half
    gray_levels = [64, 128, 192]
    labels_top = ["25% Gray", "50% Gray", "75% Gray"]
    labels_bot = ["25% Dithered", "50% Dithered", "75% Dithered"]

    col_w = w // 3
    half_h = h // 2

    for col, (gray, ltop, lbot) in enumerate(
        zip(gray_levels, labels_top, labels_bot, strict=False)
    ):
        x0 = col * col_w
        x1 = x0 + col_w if col < 2 else w

        # Solid gray band (top half)
        draw.rectangle([x0, 0, x1, half_h], fill=(gray, gray, gray))
        luma = gray
        tc = "white" if luma < 128 else "black"
        _draw_centered_text(draw, ltop, font, x0, 0, x1, half_h, tc)

        # Dithered version (bottom half): render a small patch via Pillow's convert
        patch_w = x1 - x0
        patch = Image.new("L", (patch_w, half_h), gray)
        dithered = patch.convert("1")  # Floyd-Steinberg dithering
        dithered_rgb = dithered.convert("RGB")
        img.paste(dithered_rgb, (x0, half_h))
        _draw_centered_text(draw, lbot, font, x0, half_h, x1, h, "black")

    # Draw separating lines
    draw.line([(0, half_h), (w, half_h)], fill="gray", width=1)
    draw.line([(col_w, 0), (col_w, h)], fill="gray", width=1)
    draw.line([(col_w * 2, 0), (col_w * 2, h)], fill="gray", width=1)

    return img


def make_font_resolution(w: int, h: int) -> Image.Image:
    """Text in 8/10/12/14/18/24/32 pt to find the smallest legible size."""
    img = Image.new("RGB", (w, h), "white")
    draw = ImageDraw.Draw(img)

    sizes = [8, 10, 12, 14, 18, 24, 32]
    sample = "AaBbCc 0123 Quick brown fox — ({[<>]})"

    margin = 10
    y = margin

    for pt in sizes:
        font = _default_font(pt)
        label = f"{pt}pt: {sample}"
        draw.text((margin, y), label, fill="black", font=font)
        try:
            bbox = draw.textbbox((0, 0), label, font=font)
            th = bbox[3] - bbox[1]
        except AttributeError:
            _, th = draw.textsize(label, font=font)  # type: ignore[attr-defined]
        y += th + 6
        if y > h - margin:
            break

    return img


def make_edge_sharpness(w: int, h: int) -> Image.Image:
    """Diagonal black/white edges, concentric circles, and a Siemens star."""
    img = Image.new("RGB", (w, h), "white")
    draw = ImageDraw.Draw(img)

    # --- Left third: diagonal edge ---
    third_w = w // 3
    draw.polygon([(0, 0), (third_w, 0), (0, h)], fill="black")
    draw.line([(0, 0), (third_w, h)], fill="gray", width=1)

    # --- Middle third: concentric circles ---
    cx = third_w + third_w // 2
    cy = h // 2
    max_r = min(third_w, h) // 2 - 5
    for r in range(max_r, 0, -max(1, max_r // 12)):
        color = "black" if (r // max(1, max_r // 12)) % 2 == 0 else "white"
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)

    # --- Right third: Siemens star (16 spokes) ---
    sx0 = third_w * 2
    scx = sx0 + (w - sx0) // 2
    scy = h // 2
    star_r = min(w - sx0, h) // 2 - 8
    spokes = 16
    for s in range(spokes):
        angle1 = 2 * math.pi * s / spokes
        angle2 = 2 * math.pi * (s + 0.5) / spokes
        p1 = (scx + star_r * math.cos(angle1), scy + star_r * math.sin(angle1))
        p2 = (scx, scy)
        p3 = (scx + star_r * math.cos(angle2), scy + star_r * math.sin(angle2))
        # Alternate filled/empty triangles to create star
        if s % 2 == 0:
            draw.polygon([p1, p2, p3], fill="black")

    # Add section labels
    font = _default_font(11)
    draw.text((5, 5), "Diagonal Edge", fill="white", font=font)
    draw.text((third_w + 5, 5), "Concentric Circles", fill="black", font=font)
    draw.text((sx0 + 5, 5), "Siemens Star", fill="black", font=font)

    return img


def make_full_refresh(w: int, h: int) -> Image.Image:
    """Alternating single-pixel-wide columns (black/white) to detect ghosting."""
    img = Image.new("RGB", (w, h), "white")
    pixels = img.load()
    if pixels is None:
        return img

    # Top half: alternating single-pixel columns
    for x in range(w):
        color = 0 if x % 2 == 0 else 255
        for y in range(h // 2):
            pixels[x, y] = (color, color, color)

    # Bottom half: 4-pixel-wide alternating stripes (easier for the eye)
    for x in range(w):
        stripe = (x // 4) % 2
        color = 0 if stripe == 0 else 255
        for y in range(h // 2, h):
            pixels[x, y] = (color, color, color)

    draw = ImageDraw.Draw(img)
    font = _default_font(12)
    draw.text(
        (10, 5),
        "1px alternating columns — ghosting/refresh test",
        fill="white",
        font=font,
    )
    draw.text((10, h // 2 + 5), "4px alternating stripes", fill="white", font=font)

    return img


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _default_font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    """Return a font at the requested size; falls back to default if no TTF found."""
    # Try common system fonts on Raspberry Pi / Linux / macOS
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Arial.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    # Last-resort: Pillow built-in (fixed size, ignores 'size')
    return ImageFont.load_default()


def _draw_centered_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont | ImageFont.FreeTypeFont,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    color: str,
) -> None:
    """Draw text centered within the bounding box (x0,y0)-(x1,y1)."""
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
    except AttributeError:
        tw, th = draw.textsize(text, font=font)  # type: ignore[attr-defined]
    tx = x0 + ((x1 - x0) - tw) // 2
    ty = y0 + ((y1 - y0) - th) // 2
    draw.text((tx, ty), text, fill=color, font=font)


# ---------------------------------------------------------------------------
# Profile → pattern map
# ---------------------------------------------------------------------------

ALL_PATTERNS = [
    ("01_pure_colors.png", make_pure_colors),
    ("02_grayscale_ramp.png", make_grayscale_ramp),
    ("03_dithering_grid.png", make_dithering_grid),
    ("04_font_resolution.png", make_font_resolution),
    ("05_edge_sharpness.png", make_edge_sharpness),
    ("06_full_refresh.png", make_full_refresh),
]

PROFILE_PATTERNS: dict[str, list[str]] = {
    "color": [p[0] for p in ALL_PATTERNS],
    "grayscale": [
        "02_grayscale_ramp.png",
        "03_dithering_grid.png",
        "04_font_resolution.png",
        "05_edge_sharpness.png",
        "06_full_refresh.png",
    ],
    "mono": [
        "03_dithering_grid.png",
        "06_full_refresh.png",
    ],
}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(args: argparse.Namespace | None = None) -> list[Path]:
    """Generate calibration patterns and return a list of written file paths."""
    if args is None:
        parser = _build_parser()
        args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    w, h = args.width, args.height
    enabled = set(PROFILE_PATTERNS[args.profile])

    written: list[Path] = []
    for filename, generator in ALL_PATTERNS:
        if filename not in enabled:
            continue
        img = generator(w, h)

        # For mono profile, convert to 1-bit
        if args.profile == "mono":
            img = img.convert("L").convert("1")

        dest = output_dir / filename
        img.save(dest, format="PNG")
        written.append(dest)
        print(f"  wrote {dest}")

    return written


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate e-ink display calibration test patterns."
    )
    parser.add_argument(
        "--width", type=int, default=800, help="Image width in pixels (default: 800)"
    )
    parser.add_argument(
        "--height", type=int, default=480, help="Image height in pixels (default: 480)"
    )
    parser.add_argument(
        "--output-dir",
        default="./calibration",
        help="Directory to write PNG files (default: ./calibration)",
    )
    parser.add_argument(
        "--profile",
        choices=list(PROFILE_PATTERNS),
        default="color",
        help="Pattern set: color (all 6), grayscale (5), mono (2 as 1-bit). Default: color",
    )
    return parser


if __name__ == "__main__":
    written = main()
    print(f"\nDone — {len(written)} file(s) written.")
