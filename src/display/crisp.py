"""Crisp, undithered colour conversion for rendered UI on colour e-ink panels.

Colour Inky drivers error-diffuse every frame against their palette. That is
right for photos, but a dashboard rendered from HTML is mostly flat fills,
text and thin lines: diffusion turns a light-blue icon into a faint dot
pattern and an anti-aliased edge into coloured noise. For that content each
pixel is instead snapped to one panel colour, with no error carried to its
neighbours:

* Pixels with little colour (channel spread below ``CHROMA_MIN``) are
  neutral. The page's paper tone is the most common neutral luma; a neutral
  pixel becomes ink (black on light paper, white on dark paper) when it
  differs from the paper by at least ``INK_CONTRAST``. That keeps secondary
  text, light dividers and grey anti-aliasing visible instead of letting them
  fade into the paper, and works for light-on-dark faces too.
* Clearly coloured pixels keep their hue: they take the panel colour whose hue
  is closest, compared after removing the pixel's grey component and
  normalising its spread. A pale-but-saturated icon therefore becomes solid
  blue instead of fading to white, and a muted red becomes the panel red.
  A hue with no reasonable match on the panel (blue on a black/white/red/
  yellow panel) falls back to the neutral rule.
* Photographs embedded in a dashboard (RSS thumbnails, for example) would
  posterise badly, so rectangular regions that look photographic -- clusters
  of 8x8 blocks with many distinct colours -- are error-diffused against
  *dither_palette* exactly as the driver would have done.
* A frame dominated by smooth gradients (a gradient clock face, a sky
  background) has no flat fills to keep crisp, and snapping it would cut the
  design into a few flat bands. :func:`gradient_dominated` spots such frames
  so the caller can leave the whole frame to the driver's dithering. Small
  decorative gradients (an icon, a chart fill) stay below the threshold and
  are flattened like any other colour.

Only numpy and Pillow are used; an 800x480 frame converts in a few tens of
milliseconds on a desktop.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from PIL import Image

# Channel spread (max - min, 0-255) from which a pixel counts as coloured.
CHROMA_MIN = 56
# Luma difference from the paper tone at which a neutral pixel becomes ink.
INK_CONTRAST = 56
# Largest squared distance between normalised hues that still counts as a
# match. Adjacent primaries/secondaries are 1.0 apart, so on a six-colour
# panel every hue matches; on a four-colour panel blues and greens do not.
MAX_HUE_DIST2 = 1.05

# Photo detection works on BLOCK x BLOCK tiles. A tile is busy when it holds
# at least BUSY_COLOURS distinct colours (flat UI, text and icons rarely do);
# a busy tile is a photo core when most of its 3x3 neighbourhood is busy too;
# a connected group of at least MIN_PHOTO_CORES cores is a photo, and its
# bounding box (plus one tile of margin) is dithered.
BLOCK = 8
BUSY_COLOURS = 40
CORE_NEIGHBOURS = 6
MIN_PHOTO_CORES = 6

# Gradient detection, on the same tiles: a tile is a smooth gradient when it
# holds at least SMOOTH_MIN_COLOURS distinct colours but no channel varies by
# more than SMOOTH_MAX_RANGE inside it. Anti-aliased text and icon edges jump
# from ink to paper within a tile, so their range is far larger. A frame
# where such tiles cover more than GRADIENT_SHARE of the area is left dithered.
SMOOTH_MIN_COLOURS = 4
SMOOTH_MAX_RANGE = 32
GRADIENT_SHARE = 0.25

# Integer luma weights (sum 256), ITU-R BT.601.
_LUMA_WEIGHTS = np.array([77, 150, 29], dtype=np.int32)

Palette = Sequence[Sequence[int]]


def _palette_roles(palette: Palette) -> tuple[int, int, list[int], np.ndarray]:
    """Return black index, white index, chromatic indexes and their hue vectors."""
    pal = np.asarray(palette, dtype=np.int32).reshape(-1, 3)
    luma = pal @ _LUMA_WEIGHTS
    spread = pal.max(axis=1) - pal.min(axis=1)
    chromatic = [i for i in range(len(pal)) if spread[i] > 0]
    sub = pal[chromatic]
    hues = (sub - sub.min(axis=1, keepdims=True)) / np.maximum(spread[chromatic], 1)[
        :, None
    ]
    return int(luma.argmin()), int(luma.argmax()), chromatic, hues.astype(np.float32)


def _paper_relative(
    luma: np.ndarray, counts: np.ndarray, coloured: np.ndarray, black: int, white: int
) -> np.ndarray:
    """Black/white decision per colour, relative to the paper tone.

    *luma*, *counts* and *coloured* describe the image's distinct colours;
    the paper is the luma covering the most neutral pixels.
    """
    neutral = ~coloured
    paper = (
        int(np.bincount(luma[neutral], weights=counts[neutral], minlength=256).argmax())
        if neutral.any()
        else 255
    )
    if paper >= 128:
        return np.where(luma <= paper - INK_CONTRAST, black, white).astype(np.uint8)
    return np.where(luma >= paper + INK_CONTRAST, white, black).astype(np.uint8)


def _box3(mask: np.ndarray) -> np.ndarray:
    """Count of set cells in each cell's 3x3 neighbourhood."""
    padded = np.pad(mask.astype(np.int32), 1)
    h, w = mask.shape
    total = np.zeros((h, w), dtype=np.int32)
    for i in range(3):
        for j in range(3):
            total += padded[i : i + h, j : j + w]
    return total


def _tiles(values: np.ndarray) -> np.ndarray:
    """Split ``(height, width, ...)`` into ``(h, w, BLOCK * BLOCK, ...)`` tiles."""
    h, w = values.shape[0] // BLOCK, values.shape[1] // BLOCK
    rest = values.shape[2:]
    cropped = values[: h * BLOCK, : w * BLOCK]
    tiles = cropped.reshape(h, BLOCK, w, BLOCK, *rest).swapaxes(1, 2)
    return tiles.reshape(h, w, BLOCK * BLOCK, *rest)


def _distinct_per_tile(packed: np.ndarray) -> np.ndarray:
    ordered = np.sort(_tiles(packed), axis=2)
    changes: np.ndarray = np.count_nonzero(np.diff(ordered, axis=2), axis=2)
    return changes + 1


def gradient_dominated(image: Image.Image) -> bool:
    """True when smooth gradients cover more than ``GRADIENT_SHARE`` of *image*."""
    rgb = np.asarray(image.convert("RGB"), dtype=np.int32)
    tiles = _tiles(rgb)
    if tiles.size == 0:
        return False
    packed = (rgb[..., 0] << 16) | (rgb[..., 1] << 8) | rgb[..., 2]
    value_range = (tiles.max(axis=2) - tiles.min(axis=2)).max(axis=2)
    smooth = (_distinct_per_tile(packed) >= SMOOTH_MIN_COLOURS) & (
        value_range <= SMOOTH_MAX_RANGE
    )
    return float(smooth.mean()) > GRADIENT_SHARE


def photo_regions(packed: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Return ``(left, top, right, bottom)`` boxes that look photographic.

    *packed* is the image as ``0xRRGGBB`` integers, shaped ``(height, width)``.
    """
    height, width = packed.shape
    h, w = height // BLOCK, width // BLOCK
    if h == 0 or w == 0:
        return []
    busy = _distinct_per_tile(packed) >= BUSY_COLOURS
    core = busy & (_box3(busy) >= CORE_NEIGHBOURS)

    boxes: list[tuple[int, int, int, int]] = []
    seen = np.zeros_like(core)
    for start in zip(*np.nonzero(core), strict=True):
        if seen[start]:
            continue
        seen[start] = True
        stack = [start]
        cells = []
        while stack:
            y, x = stack.pop()
            cells.append((y, x))
            for ny in range(max(y - 1, 0), min(y + 2, h)):
                for nx in range(max(x - 1, 0), min(x + 2, w)):
                    if core[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
        if len(cells) < MIN_PHOTO_CORES:
            continue
        ys = [c[0] for c in cells]
        xs = [c[1] for c in cells]
        boxes.append(
            (
                max(min(xs) - 1, 0) * BLOCK,
                max(min(ys) - 1, 0) * BLOCK,
                min((max(xs) + 2) * BLOCK, width),
                min((max(ys) + 2) * BLOCK, height),
            )
        )
    return boxes


def crisp_indices(
    image: Image.Image,
    palette: Palette,
    dither_palette: Palette | None = None,
) -> np.ndarray:
    """Map every pixel of *image* to an index into *palette*.

    *palette* lists the panel's pure colours (black, white and its
    primaries). *dither_palette*, in the same order, is what photographic
    regions are error-diffused against; it defaults to *palette*. Returns a
    ``uint8`` array shaped ``(height, width)``.
    """
    black, white, chromatic, hues = _palette_roles(palette)
    rgb_img = image.convert("RGB")
    rgb = np.asarray(rgb_img, dtype=np.int32)
    packed = (rgb[..., 0] << 16) | (rgb[..., 1] << 8) | rgb[..., 2]

    # Rendered UI has few distinct colours, so decide once per colour.
    colours, inverse, counts = np.unique(
        packed.ravel(), return_inverse=True, return_counts=True
    )
    u = np.stack([colours >> 16, (colours >> 8) & 0xFF, colours & 0xFF], axis=1)
    luma = (u @ _LUMA_WEIGHTS) >> 8
    lo = u.min(axis=1)
    spread = u.max(axis=1) - lo
    coloured = (spread >= CHROMA_MIN) & bool(chromatic)
    lut = _paper_relative(luma, counts, coloured, black, white)

    if coloured.any():
        norm = (u[coloured] - lo[coloured][:, None]).astype(np.float32)
        norm /= spread[coloured][:, None].astype(np.float32)
        dist = ((norm[:, None, :] - hues[None, :, :]) ** 2).sum(axis=2)
        best = dist.argmin(axis=1)
        matched = dist[np.arange(len(best)), best] <= MAX_HUE_DIST2
        chosen = np.asarray(chromatic, dtype=np.uint8)[best]
        lut[coloured] = np.where(matched, chosen, lut[coloured])
    out = lut[inverse].reshape(packed.shape)

    boxes = photo_regions(packed)
    if boxes:
        dpal = palette if dither_palette is None else dither_palette
        pal_img = Image.new("P", (1, 1))
        pal_img.putpalette(np.asarray(dpal, dtype=np.uint8).tobytes())
        for left, top, right, bottom in boxes:
            region = rgb_img.crop((left, top, right, bottom)).quantize(
                len(dpal), palette=pal_img, dither=Image.Dither.FLOYDSTEINBERG
            )
            out[top:bottom, left:right] = np.asarray(region, dtype=np.uint8)
    return out


def crisp_image(
    image: Image.Image, palette: Palette, dither_palette: Palette | None = None
) -> Image.Image:
    """Return *image* as RGB using only the pure *palette* colours."""
    lut = np.asarray(palette, dtype=np.uint8).reshape(-1, 3)
    return Image.fromarray(lut[crisp_indices(image, palette, dither_palette)], "RGB")


def exact_palette_image(image: Image.Image, palette: Palette) -> Image.Image:
    """Mode-P copy of an image whose every pixel is already a *palette* colour.

    The caller must have checked that; indices follow the order of *palette*.
    """
    pixels = np.asarray(image.convert("RGB"), dtype=np.uint32)
    packed = (pixels[..., 0] << 16) | (pixels[..., 1] << 8) | pixels[..., 2]
    pal_packed = np.array([(r << 16) | (g << 8) | b for r, g, b in palette])
    order = np.argsort(pal_packed)
    indices = order[np.searchsorted(pal_packed[order], packed)].astype(np.uint8)
    frame = Image.fromarray(indices, "P")
    frame.putpalette(bytes(v for colour in palette for v in colour))
    return frame
