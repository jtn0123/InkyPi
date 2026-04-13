"""Pickle-safe context for subprocess plugin execution.

``RefreshContext`` captures the minimal set of configuration values that
a subprocess worker needs to restore a functional ``Config`` singleton and
execute a plugin refresh.  By limiting the payload to primitive types and
strings, we avoid serialising the entire ``Config`` object graph — which
was fragile, especially under ``forkserver`` / ``spawn`` start methods.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from config import Config


class SupportsRefreshConfig(Protocol):
    """Config interface needed to snapshot and restore refresh state."""

    config_file: str
    current_image_file: str
    processed_image_file: str
    plugin_image_dir: str
    history_image_dir: str

    def get_resolution(self) -> tuple[int, int]: ...

    def get_config(self, key: str, default: object = ...) -> object: ...


@dataclass(frozen=True, slots=True)
class RefreshContext:
    """Immutable, pickle-safe snapshot of device configuration for subprocesses.

    All fields are primitives or strings so the dataclass can be safely
    serialised across the ``multiprocessing`` process boundary regardless
    of the start method (fork, forkserver, spawn).

    Attributes:
        config_file: Absolute path to the ``device.json`` config file.
        current_image_file: Path where the current display image is stored.
        processed_image_file: Path where the preprocessed display image is stored.
        plugin_image_dir: Directory for per-plugin cached images.
        history_image_dir: Directory for historical image snapshots.
        resolution: ``(width, height)`` tuple for the display.
        timezone: IANA timezone string (e.g. ``"America/New_York"``).
    """

    config_file: str
    current_image_file: str
    processed_image_file: str
    plugin_image_dir: str
    history_image_dir: str
    resolution: tuple[int, int]
    timezone: str

    @classmethod
    def from_config(cls, device_config: SupportsRefreshConfig) -> RefreshContext:
        """Build a ``RefreshContext`` from a live :class:`Config` instance.

        This is the canonical factory used at the application boundary
        (e.g. ``create_app()``) to snapshot the current configuration
        before handing it to ``RefreshTask``.

        Args:
            device_config: A :class:`config.Config` instance.

        Returns:
            A frozen ``RefreshContext`` dataclass.
        """
        try:
            res = device_config.get_resolution()
            width, height = int(res[0]), int(res[1])
        except Exception:
            width, height = 800, 480

        tz = "UTC"
        try:
            raw_tz = device_config.get_config("timezone", default="UTC")
            tz = str(raw_tz or "UTC")
        except Exception:
            pass

        return cls(
            config_file=str(getattr(device_config, "config_file", "")),
            current_image_file=str(getattr(device_config, "current_image_file", "")),
            processed_image_file=str(
                getattr(device_config, "processed_image_file", "")
            ),
            plugin_image_dir=str(getattr(device_config, "plugin_image_dir", "")),
            history_image_dir=str(getattr(device_config, "history_image_dir", "")),
            resolution=(width, height),
            timezone=str(tz),
        )

    def restore_child_config(self) -> Config:
        """Rebuild the ``Config`` singleton inside a subprocess from this snapshot.

        Sets the class-level path attributes on ``Config`` before
        constructing a new instance, mirroring the legacy
        ``_restore_child_config`` behaviour but sourcing values from
        this dataclass instead of a pickled ``Config`` object.

        Returns:
            A new :class:`Config` instance initialised from the snapshot paths.
        """
        from config import Config

        Config.config_file = self.config_file
        Config.current_image_file = self.current_image_file
        Config.processed_image_file = self.processed_image_file
        Config.plugin_image_dir = self.plugin_image_dir
        Config.history_image_dir = self.history_image_dir
        return Config()
