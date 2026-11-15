"""Plugin-instance lookup shared by ``RefreshTask`` and its mixins.

Every place the refresh task turns a plugin config into a plugin instance
resolves ``get_plugin_instance`` through this module at call time, so tests
substitute a fake plugin by patching ``refresh_task.plugin_lookup.get_plugin_instance``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from plugins.plugin_registry import get_plugin_instance

__all__ = ["get_plugin_instance", "_plugin_requires_api_key"]


def _plugin_requires_api_key(plugin_config: Mapping[str, Any]) -> bool:
    """Return whether ``plugin-info.json`` declares ``requires_api_key``.

    Only a progress label depends on this, so it reads the metadata rather
    than loading the plugin's code into the main process.
    """
    return plugin_config.get("requires_api_key") is True
