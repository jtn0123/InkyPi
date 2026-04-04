"""Regression guards for the legacy settings.html → schema migration (JTN-153).

These tests prevent drift back to legacy hand-built plugin templates now
that all plugins use the schema-driven form system.
"""

import glob
import os
import sys

import pytest

# Ensure src/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

# Plugins that intentionally have no settings schema
_SCHEMA_EXEMPT = {"base_plugin", "year_progress"}

# All active plugin IDs (excluding __pycache__, __fake__, and exempt plugins)
_ACTIVE_PLUGINS = [
    "ai_image",
    "ai_text",
    "apod",
    "calendar",
    "clock",
    "comic",
    "countdown",
    "github",
    "image_album",
    "image_folder",
    "image_upload",
    "image_url",
    "newspaper",
    "rss",
    "screenshot",
    "todo_list",
    "unsplash",
    "weather",
    "wpotd",
]


@pytest.mark.parametrize("plugin_id", _ACTIVE_PLUGINS)
def test_all_active_plugins_have_settings_schema(plugin_id):
    """Every active plugin must return a non-None settings schema."""
    from plugins.base_plugin.base_plugin import BasePlugin

    # Dynamically import the plugin module
    mod = __import__(f"plugins.{plugin_id}.{plugin_id}", fromlist=[plugin_id])
    # Find the plugin class (first class that inherits from BasePlugin)
    plugin_cls = None
    for attr_name in dir(mod):
        attr = getattr(mod, attr_name)
        if (
            isinstance(attr, type)
            and issubclass(attr, BasePlugin)
            and attr is not BasePlugin
        ):
            plugin_cls = attr
            break

    assert plugin_cls is not None, f"No BasePlugin subclass found in {plugin_id}"
    instance = plugin_cls({"id": plugin_id})
    schema = instance.build_settings_schema()
    assert schema is not None, (
        f"Plugin '{plugin_id}' returns None from build_settings_schema() — "
        f"all active plugins must use the schema-driven form system"
    )


def test_no_orphaned_settings_html():
    """No plugin directory (other than base_plugin) should contain a settings.html."""
    matches = sorted(glob.glob("src/plugins/*/settings.html"))
    allowed = {"src/plugins/base_plugin/settings.html"}
    orphans = [m for m in matches if m not in allowed]
    assert orphans == [], (
        f"Orphaned legacy settings.html found: {orphans}. "
        f"Use build_settings_schema() instead."
    )


@pytest.mark.parametrize("plugin_id", ["image_folder", "image_album", "image_upload"])
def test_image_plugins_have_background_fields_in_schema(plugin_id):
    """Image plugins must define backgroundOption and backgroundColor in their schema."""
    from plugins.base_plugin.base_plugin import BasePlugin

    mod = __import__(f"plugins.{plugin_id}.{plugin_id}", fromlist=[plugin_id])
    plugin_cls = None
    for attr_name in dir(mod):
        attr = getattr(mod, attr_name)
        if (
            isinstance(attr, type)
            and issubclass(attr, BasePlugin)
            and attr is not BasePlugin
        ):
            plugin_cls = attr
            break

    instance = plugin_cls({"id": plugin_id})
    schema = instance.build_settings_schema()

    # Recursively collect all field names from the schema
    field_names = set()

    def _collect_fields(obj):
        if isinstance(obj, dict):
            if "name" in obj:
                field_names.add(obj["name"])
            for v in obj.values():
                _collect_fields(v)
        elif isinstance(obj, list):
            for item in obj:
                _collect_fields(item)

    _collect_fields(schema)

    assert (
        "backgroundOption" in field_names
    ), f"Plugin '{plugin_id}' schema missing 'backgroundOption' field"
    assert (
        "backgroundColor" in field_names
    ), f"Plugin '{plugin_id}' schema missing 'backgroundColor' field"
