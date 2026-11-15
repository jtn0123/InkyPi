"""Tell the refresh loop that a route changed what it schedules."""

from __future__ import annotations

import logging

from flask import current_app

logger = logging.getLogger(__name__)


def wake_refresh_loop(reason: str) -> None:
    """Make the refresh loop re-plan its wait after a playlist or config change.

    The loop sleeps for a wait worked out from the playlists (their cycle
    times and windows) and the device interval. Without a wake-up, a change
    only takes effect when that sleep ends, which can be the full device
    interval (up to 24 hours). The change itself is already saved, so a
    failure here is logged rather than raised.
    """
    refresh_task = current_app.config.get("REFRESH_TASK")
    if refresh_task is None:
        return
    try:
        refresh_task.signal_config_change()
    except Exception:
        logger.exception("Could not wake the refresh loop after %s", reason)
