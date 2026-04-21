"""Refresh action types and request dataclass."""

import logging
import os
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from PIL import Image

from utils.image_utils import load_image_from_path

logger = logging.getLogger(__name__)


Metrics = dict[str, object]
RefreshInfo = dict[str, str]


class PluginLike(Protocol):
    """Minimum plugin interface required by refresh actions."""

    def generate_image(
        self, settings: Mapping[str, object], device_config: object
    ) -> Image.Image: ...


class DeviceConfigLike(Protocol):
    """Config surface needed by refresh actions."""

    plugin_image_dir: str


class PlaylistLike(Protocol):
    """Playlist surface needed to report refresh metadata."""

    name: str


class PluginInstanceLike(Protocol):
    """Playlist plugin-instance surface required for execution."""

    plugin_id: str
    name: str
    settings: Mapping[str, object]
    latest_refresh_time: str | None

    def get_image_path(self) -> str: ...

    def should_refresh(self, current_dt: datetime) -> bool: ...


@dataclass
class ManualUpdateRequest:
    request_id: str
    refresh_action: "RefreshAction"
    done: threading.Event = field(default_factory=threading.Event)
    # JTN-786: ``image_saved`` fires after the processed image is persisted to
    # disk but before the (slow) e-paper SPI write completes.  ``manual_update``
    # returns as soon as this event is set so the API response is not held
    # hostage by the display hardware.  ``done`` still fires at the end of the
    # full refresh and carries the final metrics/exception.
    image_saved: threading.Event = field(default_factory=threading.Event)
    image_saved_metrics: Metrics | None = None
    metrics: Metrics | None = None
    exception: BaseException | None = None


class RefreshAction:
    """Base class for a refresh action.

    Subclasses must implement :meth:`execute` to perform the refresh operation
    and return the resulting image.
    """

    def execute(
        self, plugin: PluginLike, device_config: DeviceConfigLike, current_dt: datetime
    ) -> Image.Image:
        """Execute the refresh operation and return the updated image."""
        raise NotImplementedError("Subclasses must implement the execute method.")

    def get_refresh_info(self) -> RefreshInfo:
        """Return refresh metadata as a dictionary."""
        raise NotImplementedError(
            "Subclasses must implement the get_refresh_info method."
        )

    def get_plugin_id(self) -> str:
        """Return the plugin ID associated with this refresh."""
        raise NotImplementedError("Subclasses must implement the get_plugin_id method.")


class ManualRefresh(RefreshAction):
    """Performs a manual refresh based on a plugin's ID and its associated settings.

    Attributes:
        plugin_id (str): The ID of the plugin to refresh.
        plugin_settings (dict[str, object]): The settings for the manual refresh.
    """

    def __init__(self, plugin_id: str, plugin_settings: Mapping[str, object]) -> None:
        self.plugin_id = plugin_id
        self.plugin_settings = dict(plugin_settings)

    def execute(
        self, plugin: PluginLike, device_config: DeviceConfigLike, current_dt: datetime
    ) -> Image.Image:
        """Performs a manual refresh using the stored plugin ID and settings."""
        return plugin.generate_image(self.plugin_settings, device_config)

    def get_refresh_info(self) -> RefreshInfo:
        """Return refresh metadata as a dictionary."""
        return {"refresh_type": "Manual Update", "plugin_id": self.plugin_id}

    def get_plugin_id(self) -> str:
        """Return the plugin ID associated with this refresh."""
        return self.plugin_id


class PlaylistRefresh(RefreshAction):
    """Performs a refresh using a plugin instance within a playlist context.

    Attributes:
        playlist: The playlist object associated with the refresh.
        plugin_instance: The plugin instance to refresh.
    """

    def __init__(
        self,
        playlist: PlaylistLike,
        plugin_instance: PluginInstanceLike,
        force: bool = False,
    ) -> None:
        self.playlist = playlist
        self.plugin_instance = plugin_instance
        self.force = force

    def get_refresh_info(self) -> RefreshInfo:
        """Return refresh metadata as a dictionary."""
        return {
            "refresh_type": "Playlist",
            "playlist": self.playlist.name,
            "plugin_id": self.plugin_instance.plugin_id,
            "plugin_instance": self.plugin_instance.name,
        }

    def get_plugin_id(self) -> str:
        """Return the plugin ID associated with this refresh."""
        return self.plugin_instance.plugin_id

    def execute(
        self, plugin: PluginLike, device_config: DeviceConfigLike, current_dt: datetime
    ) -> Image.Image:
        """Performs a refresh for the specified plugin instance within its playlist context."""
        # Determine the file path for the plugin's image
        plugin_image_path = os.path.join(
            device_config.plugin_image_dir, self.plugin_instance.get_image_path()
        )

        # Check if a refresh is needed based on the plugin instance's criteria
        if self.plugin_instance.should_refresh(current_dt) or self.force:
            logger.info(
                f"Refreshing plugin instance. | plugin_instance: '{self.plugin_instance.name}'"
            )
            # Generate a new image
            image = plugin.generate_image(self.plugin_instance.settings, device_config)
            image.save(plugin_image_path)
            self.plugin_instance.latest_refresh_time = current_dt.isoformat()
        else:
            logger.info(
                f"Not time to refresh plugin instance, using latest image. | plugin_instance: {self.plugin_instance.name}."
            )
            # Load the existing image from disk using standardized helper
            image = load_image_from_path(plugin_image_path)
            if image is None:
                raise RuntimeError("Failed to load existing plugin image from disk")

        return image
