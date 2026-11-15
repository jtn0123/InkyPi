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
* Anti-aliasing between two flat colours produces in-between shades, and an
  in-between shade can land on a third panel colour: green digits on a red
  face get an olive edge, which on its own reads as yellow. An uncommon
  colour lying on the straight line between two common colours is treated as
  such a blend and takes the colour of whichever side it is nearer to, so an
  edge never introduces a colour that neither side has.
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

Only numpy and Pillow are used. Analyse a frame once with :class:`Frame` and
pass it to both :func:`gradient_dominated` and :func:`crisp_image`; an
800x480 dashboard then takes a few milliseconds on a desktop and roughly
150-200 ms on a Pi Zero 2 W.
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

# An anti-aliased edge blends the two colours either side of it. The sides are
# looked for among the EDGE_SIDES most common colours that each cover at least
# EDGE_SIDE_SHARE of the frame; a blend is at least EDGE_RARITY times rarer
# than both of its sides and within EDGE_LINE_DIST (RGB units) of the straight
# line between them.
EDGE_SIDES = 12
EDGE_SIDE_SHARE = 0.001
EDGE_RARITY = 4
EDGE_LINE_DIST = 3

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
    """Split ``(height, width)`` into ``(h, w, BLOCK * BLOCK)`` tiles."""
    h, w = values.shape[0] // BLOCK, values.shape[1] // BLOCK
    cropped = values[: h * BLOCK, : w * BLOCK]
    tiles = cropped.reshape(h, BLOCK, w, BLOCK).swapaxes(1, 2)
    return tiles.reshape(h, w, BLOCK * BLOCK)


def _channel_tiles(rgb: np.ndarray) -> np.ndarray:
    """Split ``(height, width, 3)`` into contiguous ``(3, h, w, BLOCK * BLOCK)``.

    Channels come first so per-tile reductions run along the last, contiguous
    axis. Reducing a channel-last tile layout across its pixels instead takes
    several times longer on the Pi Zero 2 W (about 185 ms against 35 ms for
    an 800x480 frame).
    """
    h, w = rgb.shape[0] // BLOCK, rgb.shape[1] // BLOCK
    planes = rgb[: h * BLOCK, : w * BLOCK].transpose(2, 0, 1)
    tiles = planes.reshape(3, h, BLOCK, w, BLOCK).transpose(0, 1, 3, 2, 4)
    return np.ascontiguousarray(tiles).reshape(3, h, w, BLOCK * BLOCK)


def _distinct_per_tile(packed: np.ndarray) -> np.ndarray:
    ordered = np.sort(_tiles(packed), axis=2)
    changes: np.ndarray = np.count_nonzero(np.diff(ordered, axis=2), axis=2)
    return changes + 1


class Frame:
    """One image's pixels in the forms every crisp step reads, computed once.

    The gradient check and the conversion both need the frame as RGB, as
    packed ``0xRRGGBB`` integers and as distinct colours per tile. Building
    those costs more than either decision made from them, so the display
    analyses a frame once and passes the :class:`Frame` to both. The public
    functions also take a plain image and analyse it themselves.
    """

    __slots__ = ("distinct", "image", "packed", "rgb")

    def __init__(self, image: Image.Image) -> None:
        self.image = image.convert("RGB")
        #: ``uint8`` pixels shaped ``(height, width, 3)``.
        self.rgb = np.asarray(self.image)
        packed = self.rgb[..., 0].astype(np.int32) << 16
        packed |= self.rgb[..., 1].astype(np.int32) << 8
        packed |= self.rgb[..., 2]
        #: ``int32`` pixels as ``0xRRGGBB``, shaped ``(height, width)``.
        self.packed = packed
        #: Distinct colours in each ``BLOCK x BLOCK`` tile, shaped ``(h, w)``.
        self.distinct = _distinct_per_tile(packed)


def _as_frame(image: Image.Image | Frame) -> Frame:
    return image if isinstance(image, Frame) else Frame(image)


def gradient_dominated(image: Image.Image | Frame) -> bool:
    """True when smooth gradients cover more than ``GRADIENT_SHARE`` of *image*."""
    frame = _as_frame(image)
    if frame.distinct.size == 0:
        return False
    planes = _channel_tiles(frame.rgb)
    # uint8 is safe: a tile's maximum is never below its minimum.
    value_range = (planes.max(axis=3) - planes.min(axis=3)).max(axis=0)
    smooth = (frame.distinct >= SMOOTH_MIN_COLOURS) & (value_range <= SMOOTH_MAX_RANGE)
    return float(smooth.mean()) > GRADIENT_SHARE


def photo_regions(
    packed: np.ndarray, distinct: np.ndarray | None = None
) -> list[tuple[int, int, int, int]]:
    """Return ``(left, top, right, bottom)`` boxes that look photographic.

    *packed* is the image as ``0xRRGGBB`` integers, shaped ``(height, width)``.
    *distinct* is its distinct colours per tile when the caller already has
    them (:attr:`Frame.distinct`); otherwise they are counted here.
    """
    height, width = packed.shape
    h, w = height // BLOCK, width // BLOCK
    if h == 0 or w == 0:
        return []
    if distinct is None:
        distinct = _distinct_per_tile(packed)
    busy = distinct >= BUSY_COLOURS
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


def _settle_edge_blends(u: np.ndarray, counts: np.ndarray, lut: np.ndarray) -> None:
    """Stop anti-aliased edges introducing a colour neither side has.

    *u* holds the frame's distinct colours, *counts* how often each occurs and
    *lut* the panel index chosen for each; *lut* is corrected in place. Only
    colours whose index differs from both sides of their edge are touched, so
    grey text edges keep the weight the paper rule gave them.
    """
    common = np.argsort(counts)[::-1][:EDGE_SIDES]
    common = common[counts[common] >= EDGE_SIDE_SHARE * counts.sum()]
    chosen = lut.copy()
    points = u.astype(np.float32)
    best = np.full(len(u), np.inf, dtype=np.float32)
    for pos, a in enumerate(common):
        for b in common[pos + 1 :]:
            if chosen[a] == chosen[b]:
                continue
            line = points[b] - points[a]
            offset = points - points[a]
            along = (offset @ line) / (line @ line)
            dist2 = ((offset - along[:, None] * line) ** 2).sum(axis=1)
            blend = (
                (along > 0)
                & (along < 1)
                & (dist2 <= EDGE_LINE_DIST**2)
                & (dist2 < best)
                & (counts * EDGE_RARITY <= min(counts[a], counts[b]))
                & (chosen != chosen[a])
                & (chosen != chosen[b])
            )
            lut[blend] = np.where(along[blend] < 0.5, chosen[a], chosen[b])
            best[blend] = dist2[blend]


def crisp_indices(
    image: Image.Image | Frame,
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
    frame = _as_frame(image)
    packed = frame.packed

    # Rendered UI has few distinct colours, so decide once per colour.
    colours, counts = np.unique(packed, return_counts=True)
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
    _settle_edge_blends(u, counts, lut)
    # Spread the per-colour decisions back over the pixels through a table
    # indexed by the 24-bit colour itself, which is several times faster on
    # the Pi than asking np.unique for the inverse mapping. np.zeros leaves
    # the 16 MB table as untouched zero pages, so only the pages holding the
    # frame's colours are ever committed: a few hundred KB for rendered UI.
    table = np.zeros(1 << 24, dtype=np.uint8)
    table[colours] = lut
    out = np.take(table, packed)

    boxes = photo_regions(packed, frame.distinct)
    if boxes:
        dpal = palette if dither_palette is None else dither_palette
        pal_img = Image.new("P", (1, 1))
        pal_img.putpalette(np.asarray(dpal, dtype=np.uint8).tobytes())
        for left, top, right, bottom in boxes:
            region = frame.image.crop((left, top, right, bottom)).quantize(
                len(dpal), palette=pal_img, dither=Image.Dither.FLOYDSTEINBERG
            )
            out[top:bottom, left:right] = np.asarray(region, dtype=np.uint8)
    return out


def crisp_image(
    image: Image.Image | Frame,
    palette: Palette,
    dither_palette: Palette | None = None,
) -> Image.Image:
    """Return *image* as RGB using only the pure *palette* colours."""
    indices = Image.fromarray(crisp_indices(image, palette, dither_palette), "P")
    indices.putpalette(np.asarray(palette, dtype=np.uint8).tobytes())
    # Pillow expands palette indexes in C; indexing a numpy colour table per
    # pixel took about 80 ms of the conversion on the Pi.
    return indices.convert("RGB")


def exact_palette_image(image: Image.Image, palette: Palette) -> Image.Image:
    """Mode-P copy of an image whose every pixel is already a *palette* colour.

    The caller must have checked that, and *palette* must not repeat a colour;
    indices follow the order of *palette*. Every pixel is then at distance zero
    from exactly one entry, so Pillow's nearest-colour quantize, run in C, is
    exact. It takes about 11 ms for an 800x480 frame on the Pi Zero 2 W, where
    a numpy lookup took 73 ms.
    """
    pal_img = Image.new("P", (1, 1))
    pal_img.putpalette(bytes(v for colour in palette for v in colour))
    return image.convert("RGB").quantize(
        len(palette), palette=pal_img, dither=Image.Dither.NONE
    )
