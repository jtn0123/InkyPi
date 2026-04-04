"""Regression guards for the legacy settings.html → schema migration (JTN-153).

These tests prevent drift back to legacy hand-built plugin templates now
that all plugins use the schema-driven form system.
"""

import glob
import os
import pathlib
import sys

import pytest

# Ensure src/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

# Plugins that intentionally have no settings schema
_SCHEMA_EXEMPT = {"base_plugin", "year_progress"}


def _discover_active_plugins():
    """Dynamically discover plugin directories, excluding exempt and internal."""
    plugins_dir = pathlib.Path(__file__).parents[2] / "src" / "plugins"
    exclude = _SCHEMA_EXEMPT | {"__pycache__", "__fake__"}
    return sorted(
        d.name
        for d in plugins_dir.iterdir()
        if d.is_dir() and d.name not in exclude and not d.name.startswith("_")
    )


_ACTIVE_PLUGINS = _discover_active_plugins()


def _get_plugin_class(plugin_id):
    """Import plugin module and return the first BasePlugin subclass."""
    from plugins.base_plugin.base_plugin import BasePlugin

    mod = __import__(f"plugins.{plugin_id}.{plugin_id}", fromlist=[plugin_id])
    for attr_name in dir(mod):
        attr = getattr(mod, attr_name)
        if (
            isinstance(attr, type)
            and issubclass(attr, BasePlugin)
            and attr is not BasePlugin
        ):
            return attr
    return None


@pytest.mark.parametrize("plugin_id", _ACTIVE_PLUGINS)
def test_all_active_plugins_have_settings_schema(plugin_id):
    """Every active plugin must return a non-None settings schema."""
    plugin_cls = _get_plugin_class(plugin_id)
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
    plugin_cls = _get_plugin_class(plugin_id)
    instance = plugin_cls({"id": plugin_id})
    schema = instance.build_settings_schema()

    # Recursively collect all field names from the schema
    field_names = set()

    def _collect_fields(obj) -> None:
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
