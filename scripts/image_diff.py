#!/usr/bin/env python3
"""
Compare two PNG images and report pixel-level differences.

Usage:
    python scripts/image_diff.py IMAGE_A IMAGE_B
    python scripts/image_diff.py IMAGE_A IMAGE_B --output /tmp/diff.png
    python scripts/image_diff.py IMAGE_A IMAGE_B --threshold 10
    python scripts/image_diff.py IMAGE_A IMAGE_B --summary-only
    python scripts/image_diff.py IMAGE_A IMAGE_B --json

Reports:
  - Total pixel count
  - Changed pixel count (pixels where max channel delta > threshold)
  - Change percentage
  - Maximum channel delta found

Writes a diff PNG: image A with changed pixels overlaid in red at 50% alpha.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image


def load_images(path_a: str, path_b: str) -> tuple[Image.Image, Image.Image]:
    """Load both images, converting to RGBA for consistent channel handling."""
    img_a = Image.open(path_a).convert("RGBA")
    img_b = Image.open(path_b).convert("RGBA")
    return img_a, img_b


def resize_to_match(img_a: Image.Image, img_b: Image.Image) -> Image.Image:
    """Resize img_b to match img_a dimensions if they differ."""
    if img_b.size != img_a.size:
        img_b = img_b.resize(img_a.size, Image.LANCZOS)
    return img_b


def compute_diff(
    img_a: Image.Image, img_b: Image.Image, threshold: int
) -> tuple[int, int, int]:
    """
    Compute per-pixel difference statistics.

    Returns:
        (total_pixels, changed_pixels, max_channel_delta)
    """
    pixels_a = img_a.load()
    pixels_b = img_b.load()
    width, height = img_a.size
    total_pixels = width * height

    changed_pixels = 0
    max_channel_delta = 0

    for y in range(height):
        for x in range(width):
            pa = pixels_a[x, y]  # type: ignore[index]
            pb = pixels_b[x, y]  # type: ignore[index]
            # Compare only RGB channels (ignore alpha for "changed" determination)
            channel_delta = max(abs(int(pa[c]) - int(pb[c])) for c in range(3))
            if channel_delta > max_channel_delta:
                max_channel_delta = channel_delta
            if channel_delta > threshold:
                changed_pixels += 1

    return total_pixels, changed_pixels, max_channel_delta


def build_diff_image(
    img_a: Image.Image, img_b: Image.Image, threshold: int
) -> Image.Image:
    """
    Build a visual diff image: img_a with changed pixels overlaid in red at 50% alpha.

    Changed pixels are those where any RGB channel differs by more than threshold.
    """
    pixels_a = img_a.load()
    pixels_b = img_b.load()
    width, height = img_a.size

    # Start with a copy of img_a
    diff_img = img_a.copy()
    diff_pixels = diff_img.load()

    # Red overlay pixel (R=255, G=0, B=0, A=128 for 50% alpha blended into RGBA)
    for y in range(height):
        for x in range(width):
            pa = pixels_a[x, y]  # type: ignore[index]
            pb = pixels_b[x, y]  # type: ignore[index]
            channel_delta = max(abs(int(pa[c]) - int(pb[c])) for c in range(3))
            if channel_delta > threshold:
                # Blend 50% red over the original pixel
                r = int(pa[0] * 0.5 + 255 * 0.5)
                g = int(pa[1] * 0.5 + 0 * 0.5)
                b = int(pa[2] * 0.5 + 0 * 0.5)
                a = pa[3]
                diff_pixels[x, y] = (r, g, b, a)  # type: ignore[index]

    return diff_img


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare two PNG images and report pixel-level differences."
    )
    parser.add_argument("IMAGE_A", help="Path to the first (reference) image")
    parser.add_argument("IMAGE_B", help="Path to the second (comparison) image")
    parser.add_argument(
        "--output",
        "-o",
        default="./diff.png",
        help="Output path for the diff PNG (default: ./diff.png)",
    )
    parser.add_argument(
        "--threshold",
        "-t",
        type=int,
        default=5,
        help="Per-channel difference threshold (default: 5). Pixels with max channel "
        "delta <= threshold are treated as unchanged.",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print statistics only; skip writing the diff PNG.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output statistics as JSON instead of human-readable text.",
    )
    return parser.parse_args(argv)


def run(argv: list[str] | None = None) -> dict:
    """
    Main entry point. Returns a dict with diff statistics.

    Useful for programmatic use and testing.
    """
    args = parse_args(argv)

    img_a, img_b = load_images(args.IMAGE_A, args.IMAGE_B)
    img_b = resize_to_match(img_a, img_b)

    total_pixels, changed_pixels, max_channel_delta = compute_diff(
        img_a, img_b, args.threshold
    )
    change_pct = (changed_pixels / total_pixels * 100) if total_pixels > 0 else 0.0

    stats = {
        "image_a": args.IMAGE_A,
        "image_b": args.IMAGE_B,
        "total_pixels": total_pixels,
        "changed_pixels": changed_pixels,
        "change_percentage": round(change_pct, 4),
        "max_channel_delta": max_channel_delta,
        "threshold": args.threshold,
        "diff_output": None if args.summary_only else args.output,
    }

    if not args.summary_only:
        diff_img = build_diff_image(img_a, img_b, args.threshold)
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        diff_img.save(output_path)
        stats["diff_output"] = str(output_path)

    if args.json_output:
        print(json.dumps(stats, indent=2))
    else:
        print(f"Image A:           {args.IMAGE_A}")
        print(f"Image B:           {args.IMAGE_B}")
        print(f"Total pixels:      {total_pixels:,}")
        print(f"Changed pixels:    {changed_pixels:,}")
        print(f"Change percentage: {change_pct:.4f}%")
        print(f"Max channel delta: {max_channel_delta}")
        if not args.summary_only:
            print(f"Diff image:        {stats['diff_output']}")

    return stats


if __name__ == "__main__":
    run(sys.argv[1:])
