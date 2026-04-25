"""Fallback image renderer for plugin failure notifications.

When a plugin's generate_image() raises, the display would otherwise stay
frozen on the previous image (silent lie).  This module provides a small
helper that renders a human-readable error card so the user sees *something*
changed, rather than stale content.

JTN-779: the card must not leak implementation details (e.g. Python exception
class names) to end users.  We render a friendly message derived from the raw
exception via :func:`sanitize_error_message`, while the caller keeps the raw
class + message in logs for operators.
"""

import logging
import re
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# Maximum characters for the error message before truncation
_MAX_MSG_LEN = 120
# Fallback font size as a fraction of image width
_FONT_SCALE = 0.028

# Generic message used when no known pattern matches.  Intentionally avoids
# Python-specific jargon ("RuntimeError", "exception", "traceback") so the
# user sees something actionable but neutral.
_GENERIC_FALLBACK = (
    "This plugin failed to render. Check its configuration or try again later."
)

# Ordered list of (regex pattern, friendly message) tuples.  The first pattern
# to match the raw error message wins.  Patterns are matched case-insensitively
# against the raw exception string (after any ``ClassName:`` prefix has been
# stripped).  Keep this list short and focused on user-visible validation
# errors — deep technical errors should fall through to the generic message.
_FRIENDLY_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # URL validation (JTN-776 / JTN-779) — screenshot, image_url, image_album
    (
        re.compile(r"URL scheme must be http or https", re.IGNORECASE),
        "The URL you entered is not allowed. It must start with http:// or https://.",
    ),
    (
        re.compile(r"URL host is required", re.IGNORECASE),
        "The URL you entered is missing a host. Please enter a full URL like https://example.com.",
    ),
    (
        re.compile(
            r"URL host resolves to a (?:loopback|private|reserved|link-local|multicast|unspecified) address",
            re.IGNORECASE,
        ),
        "That URL points to a private or local address, which is not allowed.",
    ),
    (
        re.compile(r"^Invalid URL\b", re.IGNORECASE),
        "The URL you entered is not valid. Please check it and try again.",
    ),
    # Network timeouts / connection errors — common across HTTP plugins
    (
        re.compile(
            r"\b(?:timed out|timeout|ReadTimeout|ConnectTimeout)\b", re.IGNORECASE
        ),
        "The request timed out. The remote server did not respond in time.",
    ),
    (
        re.compile(
            r"\b(?:ConnectionError|Failed to establish a new connection|Name or service not known|NameResolutionError)\b",
            re.IGNORECASE,
        ),
        "Could not reach the remote server. Check your network or the configured URL.",
    ),
    # Auth / API-key style errors
    (
        re.compile(
            r"\b(?:API key|api_key|apikey)\b.*(?:missing|required|invalid|unauthorized)",
            re.IGNORECASE,
        ),
        "This plugin is missing a valid API key. Update its settings.",
    ),
    (
        re.compile(r"\b(?:401|Unauthorized|Forbidden|403)\b"),
        "The remote service rejected the request (authentication failed).",
    ),
)

# Matches a leading "ExceptionClassName: " prefix, e.g. "RuntimeError: boom".
# Anchored at the start of the string; the class must be a valid Python
# identifier ending with ``Error``, ``Exception``, or ``Warning`` to avoid
# stripping legitimate user text that happens to contain a colon.
_CLASS_PREFIX_RE = re.compile(
    r"^\s*(?P<cls>[A-Z][A-Za-z0-9_]*(?:Error|Exception|Warning))\s*:\s*"
)


def strip_class_prefix(message: str) -> str:
    """Remove a leading ``ExceptionClass:`` prefix from ``message``.

    Examples:
        >>> strip_class_prefix("RuntimeError: boom")
        'boom'
        >>> strip_class_prefix("some user text: with colon")
        'some user text: with colon'
    """
    if not message:
        return ""
    return _CLASS_PREFIX_RE.sub("", message, count=1).strip()


def sanitize_error_message(
    raw_message: str | None, *, error_class: str | None = None
) -> str:
    """Convert a raw exception message into a user-friendly string.

    The returned string:

    * never includes a ``ClassName:`` prefix,
    * is a plain-English sentence when the raw message matches a known
      validation pattern,
    * otherwise falls back to a generic "plugin failed to render" line.

    Args:
        raw_message: The raw ``str(exc)`` string.
        error_class: Optional exception class name.  Only used to decide
            whether to strip a leading ``cls:`` prefix; never surfaces in the
            returned string.

    Returns:
        A user-friendly message with no Python-specific jargon.
    """
    if raw_message is None:
        raw_message = ""

    # Strip a "ClassName: " prefix if present (e.g. when the raw message was
    # formatted with ``f"{type(exc).__name__}: {exc}"`` somewhere upstream).
    cleaned = strip_class_prefix(str(raw_message))

    # Defensive: if the caller passed only the class name and nothing else,
    # fall through to the generic message.
    if not cleaned or (error_class and cleaned == error_class):
        return _GENERIC_FALLBACK

    for pattern, friendly in _FRIENDLY_PATTERNS:
        if pattern.search(cleaned):
            return friendly

    # No known pattern matched — don't echo the raw message back to the user.
    # The raw text is still available in logs for operators to diagnose.
    return _GENERIC_FALLBACK


def render_error_image(
    width: int,
    height: int,
    plugin_id: str,
    instance_name: str | None,
    error_class: str,
    error_message: str,
    timestamp: str | None = None,
) -> Any:
    """Render a plain error-card image sized to the display dimensions.

    Uses only PIL primitives (no custom fonts) so it never fails due to
    missing font files.  The card shows:
      - "Plugin Error" header
      - plugin id / instance name
      - a **sanitised**, user-friendly message (never the Python exception
        class name — see :func:`sanitize_error_message` and JTN-779)
      - ISO timestamp

    Args:
        width: Target image width in pixels.
        height: Target image height in pixels.
        plugin_id: Plugin identifier string.
        instance_name: Instance name or None.
        error_class: Exception class name (e.g. ``"RuntimeError"``).  Retained
            in the signature for call-site clarity and for logging upstream,
            but deliberately **not** rendered on the card.
        error_message: Raw ``str(exc)``.  Will be passed through
            :func:`sanitize_error_message` before display.
        timestamp: ISO timestamp string; defaults to current UTC time.

    Returns:
        A new RGBA :class:`PIL.Image.Image` containing the error card.
    """
    from PIL import Image, ImageDraw

    if timestamp is None:
        timestamp = datetime.now(UTC).isoformat(timespec="seconds")

    friendly = sanitize_error_message(error_message, error_class=error_class)
    short_msg = friendly[:_MAX_MSG_LEN]
    if len(friendly) > _MAX_MSG_LEN:
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
        short_msg,
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
