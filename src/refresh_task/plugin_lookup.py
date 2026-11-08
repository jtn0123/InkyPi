"""Plugin-instance lookup shared by ``RefreshTask`` and its mixins.

Every place the refresh task turns a plugin config into a plugin instance
resolves ``get_plugin_instance`` through this module at call time, so tests
substitute a fake plugin by patching ``refresh_task.plugin_lookup.get_plugin_instance``.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from plugins.plugin_registry import get_plugin_instance

# Moved out of task.py; keeps the original logger name so log records, level
# configuration and log-capturing tests see exactly what they did before.
logger = logging.getLogger("refresh_task.task")

__all__ = ["get_plugin_instance", "_plugin_requires_api_key"]


def _plugin_requires_api_key(plugin_config: Mapping[str, Any]) -> bool:
    """Return whether plugin metadata declares API-key configuration."""
    plugin_id = plugin_config.get("id")
    if not isinstance(plugin_id, str):
        return False

    try:
        plugin = get_plugin_instance(dict(plugin_config))
    except Exception:
        logger.debug(
            "Could not inspect API-key metadata for plugin %s",
            plugin_id,
            exc_info=True,
        )
        return False

    if getattr(plugin, "requires_api_key", False):
        return True

    try:
        template = plugin.generate_settings_template()
    except Exception:
        logger.debug(
            "Could not inspect settings template for plugin %s",
            plugin_id,
            exc_info=True,
        )
        return False

    return isinstance(template, Mapping) and "api_key" in template
