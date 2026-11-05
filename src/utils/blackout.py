"""Blackout / kill switch state (B12).

Blackout pauses every scheduled refresh and blanks the panel to white — for
guests, photos, or a plugin misbehaving while nobody is home. The state lives
in the device config (``"blackout"``) so it survives a restart: a device that
reboots mid-blackout comes back still paused, and the e-ink panel still shows
the white frame it was left on.

Only the state lives here. The routes are in :mod:`blueprints.blackout`, and
the pause itself is enforced by the refresh loop (``RefreshTask``), which is
the only thing that schedules refreshes.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

CONFIG_KEY = "blackout"

#: Shown to anyone who asks for a refresh while the display is blacked out.
BLOCKED_MESSAGE = (
    "Display is in blackout: refreshes are paused. "
    "Resume it first (DELETE /api/blackout or GET /api/blackout?off=1)."
)


class BlackoutActiveError(RuntimeError):
    """Raised when a refresh is requested while blackout is active."""

    def __init__(self, message: str = BLOCKED_MESSAGE) -> None:
        super().__init__(message)


def get_state(device_config: Any) -> dict[str, Any]:
    """Return ``{"active": bool, "since": iso | None}`` for *device_config*."""
    try:
        raw = device_config.get_config(CONFIG_KEY, default=None)
    except Exception:  # noqa: BLE001 — a config read must never break a refresh
        logger.debug("blackout: could not read state", exc_info=True)
        raw = None
    if not isinstance(raw, dict):
        return {"active": False, "since": None}
    since = raw.get("since")
    return {
        "active": raw.get("active") is True,
        "since": since if isinstance(since, str) else None,
    }


def is_active(device_config: Any) -> bool:
    """True while the display is blacked out."""
    return bool(get_state(device_config)["active"])


def set_active(device_config: Any, active: bool) -> dict[str, Any]:
    """Persist the blackout flag and return the new state."""
    state: dict[str, Any] = {
        "active": bool(active),
        "since": datetime.now(UTC).isoformat() if active else None,
    }
    device_config.update_value(CONFIG_KEY, state, write=True)
    logger.info("blackout: %s", "activated" if active else "lifted")
    return state


def blank_image(device_config: Any) -> Any:
    """A white frame at the panel's resolution."""
    from PIL import Image

    width, height = device_config.get_resolution()
    return Image.new("RGB", (int(width), int(height)), "white")
