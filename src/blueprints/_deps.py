"""Typed access to the services ``create_app`` keeps on ``app.config``.

``inkypi._init_core_services`` stores the device ``Config``, the
``DisplayManager`` and the ``RefreshTask`` under ``DEVICE_CONFIG``,
``DISPLAY_MANAGER`` and ``REFRESH_TASK``. Read straight from
``current_app.config`` they are ``Any``, so mypy could not check a single call
a route made on them. Routes get them from these functions instead.

All three are set before the app serves a request, the refresh task included:
in web-only mode it exists but its thread never starts. So none of these
returns None, and a missing key is a wiring bug that raises ``KeyError``.

The functions cast rather than check the type, so a test can store a fake
under the same key.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from flask import current_app

if TYPE_CHECKING:
    from config import Config
    from display.display_manager import DisplayManager
    from refresh_task.task import RefreshTask


def get_device_config() -> Config:
    """The device settings, playlists and plugin instances (``DEVICE_CONFIG``)."""
    return cast("Config", current_app.config["DEVICE_CONFIG"])


def get_refresh_task() -> RefreshTask:
    """The refresh loop, running or not (``REFRESH_TASK``)."""
    return cast("RefreshTask", current_app.config["REFRESH_TASK"])


def get_display_manager() -> DisplayManager:
    """The panel driver and its image pipeline (``DISPLAY_MANAGER``)."""
    return cast("DisplayManager", current_app.config["DISPLAY_MANAGER"])
