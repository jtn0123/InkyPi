"""Repository for loading and persisting RefreshInfo state.

Extracted from ``Config`` to separate refresh-state persistence from the
main config god-object.
"""

import logging
from typing import Any

from model import RefreshInfo

logger = logging.getLogger(__name__)

RefreshInfoDict = dict[str, Any]


class RefreshInfoRepository:
    """Loads and provides access to a :class:`RefreshInfo` instance.

    The repository is initialised from a raw config dict (the ``refresh_info``
    sub-key) and exposes the resulting model object.
    """

    refresh_info: RefreshInfo

    def __init__(self, raw_data: RefreshInfoDict | None = None):
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

    def to_dict(self) -> RefreshInfoDict:
        """Serialise the current state for inclusion in the config file."""
        refresh_dict: RefreshInfoDict = {
            "refresh_time": self.refresh_info.refresh_time,
            "image_hash": self.refresh_info.image_hash,
            "refresh_type": self.refresh_info.refresh_type,
            "plugin_id": self.refresh_info.plugin_id,
        }
        if self.refresh_info.playlist:
            refresh_dict["playlist"] = self.refresh_info.playlist
        if self.refresh_info.plugin_instance:
            refresh_dict["plugin_instance"] = self.refresh_info.plugin_instance
        if self.refresh_info.request_ms is not None:
            refresh_dict["request_ms"] = self.refresh_info.request_ms
        if self.refresh_info.display_ms is not None:
            refresh_dict["display_ms"] = self.refresh_info.display_ms
        if self.refresh_info.generate_ms is not None:
            refresh_dict["generate_ms"] = self.refresh_info.generate_ms
        if self.refresh_info.preprocess_ms is not None:
            refresh_dict["preprocess_ms"] = self.refresh_info.preprocess_ms
        if self.refresh_info.used_cached is not None:
            refresh_dict["used_cached"] = self.refresh_info.used_cached
        if getattr(self.refresh_info, "benchmark_id", None) is not None:
            refresh_dict["benchmark_id"] = self.refresh_info.benchmark_id
        if getattr(self.refresh_info, "plugin_meta", None) is not None:
            refresh_dict["plugin_meta"] = self.refresh_info.plugin_meta
        return refresh_dict

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _load(data: RefreshInfoDict | None) -> RefreshInfo:
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
