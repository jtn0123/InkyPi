"""Repository for loading and persisting RefreshInfo state.

Extracted from ``Config`` to separate refresh-state persistence from the
main config god-object.
"""

import logging

from model import RefreshInfo

logger = logging.getLogger(__name__)


class RefreshInfoRepository:
    """Loads and provides access to a :class:`RefreshInfo` instance.

    The repository is initialised from a raw config dict (the ``refresh_info``
    sub-key) and exposes the resulting model object.
    """

    def __init__(self, raw_data: dict | None = None):
        self.refresh_info = self._load(raw_data)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self) -> RefreshInfo:
        """Return the current :class:`RefreshInfo`."""
        return self.refresh_info

    def set(self, refresh_info: RefreshInfo) -> None:
        """Replace the current :class:`RefreshInfo`."""
        self.refresh_info = refresh_info

    def to_dict(self) -> dict:
        """Serialise the current state for inclusion in the config file."""
        return self.refresh_info.to_dict()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _load(data: dict | None) -> RefreshInfo:
        """Parse *data* into a :class:`RefreshInfo`, falling back to defaults."""
        data = data if isinstance(data, dict) else {}
        try:
            required = {"refresh_type", "plugin_id", "refresh_time", "image_hash"}
            if not required.issubset(data.keys()):
                raise ValueError("refresh_info missing required keys")
            return RefreshInfo.from_dict(data)
        except (KeyError, TypeError, ValueError) as e:
            logger.warning("Invalid refresh_info in config, using defaults: %s", e)
            return RefreshInfo("Manual Update", "", None, None)
