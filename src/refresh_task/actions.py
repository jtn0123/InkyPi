"""Refresh action types and request dataclass."""

import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime

from utils.image_utils import load_image_from_path

logger = logging.getLogger(__name__)


@dataclass
class ManualUpdateRequest:
    request_id: str
    refresh_action: "RefreshAction"
    done: threading.Event = field(default_factory=threading.Event)
    metrics: dict | None = None
    exception: BaseException | None = None


class RefreshAction:
    """Base class for a refresh action.

    Subclasses must implement :meth:`execute` to perform the refresh operation
    and return the resulting image.
    """

    def execute(self, plugin, device_config, current_dt):
        """Execute the refresh operation and return the updated image."""
        raise NotImplementedError("Subclasses must implement the execute method.")

    def get_refresh_info(self):
        """Return refresh metadata as a dictionary."""
        raise NotImplementedError(
            "Subclasses must implement the get_refresh_info method."
        )

    def get_plugin_id(self):
        """Return the plugin ID associated with this refresh."""
        raise NotImplementedError("Subclasses must implement the get_plugin_id method.")


class ManualRefresh(RefreshAction):
    """Performs a manual refresh based on a plugin's ID and its associated settings.

    Attributes:
        plugin_id (str): The ID of the plugin to refresh.
        plugin_settings (dict): The settings for the manual refresh.
    """

    def __init__(self, plugin_id: str, plugin_settings: dict):
        self.plugin_id = plugin_id
        self.plugin_settings = plugin_settings

    def execute(self, plugin, device_config, current_dt: datetime):
        """Performs a manual refresh using the stored plugin ID and settings."""
        return plugin.generate_image(self.plugin_settings, device_config)

    def get_refresh_info(self):
        """Return refresh metadata as a dictionary."""
        return {"refresh_type": "Manual Update", "plugin_id": self.plugin_id}

    def get_plugin_id(self):
        """Return the plugin ID associated with this refresh."""
        return self.plugin_id


class PlaylistRefresh(RefreshAction):
    """Performs a refresh using a plugin instance within a playlist context.

    Attributes:
        playlist: The playlist object associated with the refresh.
        plugin_instance: The plugin instance to refresh.
    """

    def __init__(self, playlist, plugin_instance, force=False):
        self.playlist = playlist
        self.plugin_instance = plugin_instance
        self.force = force

    def get_refresh_info(self):
        """Return refresh metadata as a dictionary."""
        return {
            "refresh_type": "Playlist",
            "playlist": self.playlist.name,
            "plugin_id": self.plugin_instance.plugin_id,
            "plugin_instance": self.plugin_instance.name,
        }

    def get_plugin_id(self):
        """Return the plugin ID associated with this refresh."""
        return self.plugin_instance.plugin_id

    def execute(self, plugin, device_config, current_dt: datetime):
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
