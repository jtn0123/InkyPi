"""Fallback image renderer for plugin failure notifications.

When a plugin's generate_image() raises, the display would otherwise stay
frozen on the previous image (silent lie).  This module provides a small
helper that renders a human-readable error card so the user sees *something*
changed, rather than stale content.
"""

import logging
from datetime import UTC, datetime

from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)

# Maximum characters for the error message before truncation
_MAX_MSG_LEN = 120
# Fallback font size as a fraction of image width
_FONT_SCALE = 0.028


def render_error_image(
    width: int,
    height: int,
    plugin_id: str,
    instance_name: str | None,
    error_class: str,
    error_message: str,
    timestamp: str | None = None,
) -> Image.Image:
    """Render a plain error-card image sized to the display dimensions.

    Uses only PIL primitives (no custom fonts) so it never fails due to
    missing font files.  The card shows:
      - "Plugin Error" header
      - plugin id / instance name
      - error class + truncated message
      - ISO timestamp

    Args:
        width: Target image width in pixels.
        height: Target image height in pixels.
        plugin_id: Plugin identifier string.
        instance_name: Instance name or None.
        error_class: Exception class name (e.g. ``"RuntimeError"``).
        error_message: Exception message, truncated to ``_MAX_MSG_LEN`` chars.
        timestamp: ISO timestamp string; defaults to current UTC time.

    Returns:
        A new RGBA :class:`PIL.Image.Image` containing the error card.
    """
    if timestamp is None:
        timestamp = datetime.now(UTC).isoformat(timespec="seconds")

    short_msg = error_message[:_MAX_MSG_LEN]
    if len(error_message) > _MAX_MSG_LEN:
        short_msg += "…"

    img = Image.new("RGBA", (width, height), (255, 255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Red error bar across the top
    bar_h = max(6, height // 20)
    draw.rectangle([(0, 0), (width, bar_h)], fill=(220, 50, 50, 255))

    font_size = max(10, int(width * _FONT_SCALE))
    line_gap = int(font_size * 1.6)
    margin = max(12, int(width * 0.03))

    lines = [
        "Plugin Error",
        "",
        f"Plugin:   {plugin_id}",
        f"Instance: {instance_name or '(none)'}",
        "",
        f"{error_class}: {short_msg}",
        "",
        f"Time: {timestamp}",
    ]

    try:
        from utils.app_utils import get_font

        font_header = get_font("Jost", font_size=int(font_size * 1.4))
        font_body = get_font("Jost", font_size=font_size)
    except Exception:
        font_header = None
        font_body = None

    y = bar_h + margin
    for i, line in enumerate(lines):
        font = font_header if i == 0 else font_body
        color = (180, 20, 20, 255) if i == 0 else (40, 40, 40, 255)
        draw.text((margin, y), line, fill=color, font=font)
        y += line_gap

    return img
