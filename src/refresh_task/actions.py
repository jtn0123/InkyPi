"""Refresh action types and request dataclass."""

import logging
import os
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, TypedDict

from PIL import Image

from utils.image_utils import load_image_from_path

logger = logging.getLogger(__name__)


Metrics = dict[str, object]
RefreshInfo = dict[str, str]


class StateDelta(TypedDict, total=False):
    """Plugin-instance state changed by one ``execute()`` call.

    In ``process`` isolation ``execute()`` runs against the child's copy of the
    plugin instance, so anything it changes is lost when the child exits. The
    worker ships this delta back on the result queue and the parent commits it
    to the live instance under the config lock.
    """

    latest_refresh_time: str
    # Only keys the plugin added or changed (e.g. image_upload's rotating
    # ``image_index``), so a concurrent settings edit in the web UI is not
    # overwritten wholesale.
    settings: dict[str, object]


class PluginLike(Protocol):
    """Minimum plugin interface required by refresh actions."""

    def generate_image(
        self, settings: Mapping[str, object], device_config: object
    ) -> Image.Image | None:
        """Mirrors ``BasePlugin.generate_image``, ``None`` included.

        This protocol declared a bare ``Image.Image`` after the base class was
        widened to allow ``None`` for control-only plugins, so every caller
        type-checked against a contract the implementation no longer honoured.
        That is how the missing ``None`` guard below went unnoticed.
        """
        ...


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
    latest_refresh_time: str | None

    # Read-only here: a mutable protocol attribute is invariant, so the real
    # PluginInstance (``dict[str, Any]`` settings) would not satisfy it.
    @property
    def settings(self) -> Mapping[str, object]: ...

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
    ) -> Image.Image | None:
        """Execute the refresh operation and return the updated image.

        ``None`` means the plugin produced no image on purpose — a control-only
        plugin whose point is the side effect. Callers must treat that as a
        completed refresh with nothing to display, not as a failure.
        """
        raise NotImplementedError("Subclasses must implement the execute method.")

    def get_refresh_info(self) -> RefreshInfo:
        """Return refresh metadata as a dictionary."""
        raise NotImplementedError(
            "Subclasses must implement the get_refresh_info method."
        )

    def get_plugin_id(self) -> str:
        """Return the plugin ID associated with this refresh."""
        raise NotImplementedError("Subclasses must implement the get_plugin_id method.")

    def state_delta(self) -> StateDelta:
        """Return the model state changed by the most recent :meth:`execute`."""
        return {}

    def adopt_state_delta(self, delta: StateDelta) -> None:
        """Record a delta produced by :meth:`execute` in a worker process."""

    def commit_state(self) -> None:
        """Apply the recorded delta to the live model objects.

        Callers must hold the config lock (``Config.update_atomic``) so the
        change cannot interleave with a concurrent snapshot/rollback.
        """


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
    ) -> Image.Image | None:
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
        self._state_delta: StateDelta = {}

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

    def state_delta(self) -> StateDelta:
        """Return the plugin-instance state changed by the last :meth:`execute`."""
        return self._state_delta.copy()

    def adopt_state_delta(self, delta: StateDelta) -> None:
        """Record a delta produced by :meth:`execute` in a worker process."""
        self._state_delta = delta.copy()

    def commit_state(self) -> None:
        """Apply the recorded delta to the live plugin instance."""
        refreshed_at = self._state_delta.get("latest_refresh_time")
        if refreshed_at is not None:
            self.plugin_instance.latest_refresh_time = refreshed_at
        changed_settings = self._state_delta.get("settings")
        settings = self.plugin_instance.settings
        if changed_settings and isinstance(settings, dict):
            settings.update(changed_settings)

    def _record_refresh(
        self, current_dt: datetime, settings_before: Mapping[str, object]
    ) -> None:
        """Advance the refresh timestamp and remember what changed."""
        refreshed_at = current_dt.isoformat()
        self.plugin_instance.latest_refresh_time = refreshed_at
        delta = StateDelta(latest_refresh_time=refreshed_at)
        missing = object()
        changed_settings = {
            key: value
            for key, value in self.plugin_instance.settings.items()
            if settings_before.get(key, missing) != value
        }
        if changed_settings:
            delta["settings"] = changed_settings
        self._state_delta = delta

    def execute(
        self, plugin: PluginLike, device_config: DeviceConfigLike, current_dt: datetime
    ) -> Image.Image | None:
        """Performs a refresh for the specified plugin instance within its playlist context."""
        # Determine the file path for the plugin's image
        plugin_image_path = os.path.join(
            device_config.plugin_image_dir, self.plugin_instance.get_image_path()
        )

        self._state_delta = {}
        # Check if a refresh is needed based on the plugin instance's criteria
        if self.plugin_instance.should_refresh(current_dt) or self.force:
            logger.info(
                f"Refreshing plugin instance. | plugin_instance: '{self.plugin_instance.name}'"
            )
            # Plugins may write state back into their settings (image_upload's
            # rotating index); snapshot first so the change can be shipped
            # back from a worker process.
            settings_before = dict(self.plugin_instance.settings)
            # Generate a new image
            image = plugin.generate_image(self.plugin_instance.settings, device_config)
            if image is None:
                # A control-only plugin produced no image on purpose. There is
                # nothing to persist, but the refresh did happen, so the
                # timestamp still advances — otherwise the plugin is retried
                # every cycle. RefreshTask handles the None from here.
                self._record_refresh(current_dt, settings_before)
                return None
            image.save(plugin_image_path)
            self._record_refresh(current_dt, settings_before)
        else:
            logger.info(
                f"Not time to refresh plugin instance, using latest image. | plugin_instance: {self.plugin_instance.name}."
            )
            # Load the existing image from disk using standardized helper
            image = load_image_from_path(plugin_image_path)
            if image is None:
                raise RuntimeError("Failed to load existing plugin image from disk")

        return image
