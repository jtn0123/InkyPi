# app_registry.py

import importlib
import logging
import os
import sys
from pathlib import Path

from utils.app_utils import resolve_path

logger = logging.getLogger(__name__)
PLUGINS_DIR = "plugins"
PLUGIN_CLASSES = {}


def _is_dev_mode() -> bool:
    env_mode = (
        os.getenv("INKYPI_ENV", "").strip() or os.getenv("FLASK_ENV", "").strip()
    ).lower()
    return env_mode in ("dev", "development")


def _load_single_plugin_instance(plugin_config):
    plugin_id = plugin_config.get("id")
    module_name = f"plugins.{plugin_id}.{plugin_id}"
    try:
        if _is_dev_mode() and module_name in sys.modules:
            module = importlib.reload(sys.modules[module_name])
        else:
            module = importlib.import_module(module_name)
        plugin_cls = getattr(module, plugin_config.get("class"), None)
        if not plugin_cls:
            raise ImportError(
                f"Class '{plugin_config.get('class')}' not found in module {module_name}"
            )
        return plugin_cls(plugin_config)
    except ImportError as e:
        logging.error(f"Failed to import plugin module {module_name}: {e}")
        raise


def load_plugins(plugins_config):
    plugins_module_path = Path(resolve_path(PLUGINS_DIR))
    for plugin in plugins_config:
        plugin_id = plugin.get("id")
        if plugin.get("disabled", False):
            logging.info(f"Plugin {plugin_id} is disabled, skipping.")
            continue

        plugin_dir = plugins_module_path / plugin_id
        if not plugin_dir.is_dir():
            logging.error(
                f"Could not find plugin directory {plugin_dir} for '{plugin_id}', skipping."
            )
            continue

        module_path = plugin_dir / f"{plugin_id}.py"
        if not module_path.is_file():
            logging.error(
                f"Could not find module path {module_path} for '{plugin_id}', skipping."
            )
            continue

        # In dev mode, instances will be re-created on demand to enable hot reload.
        # In non-dev, pre-load and cache instances for performance.
        if not _is_dev_mode():
            try:
                PLUGIN_CLASSES[plugin_id] = _load_single_plugin_instance(plugin)
            except Exception:
                # Error already logged by loader; continue to next plugin
                continue


def get_plugin_instance(plugin_config):
    plugin_id = plugin_config.get("id")

    # In dev mode, always (re)load and re-instantiate to pick up code changes.
    if _is_dev_mode():
        return _load_single_plugin_instance(plugin_config)

    # Retrieve cached instance if available
    instance = PLUGIN_CLASSES.get(plugin_id)
    if instance:
        return instance

    # Fallback: attempt to load a single plugin on demand
    instance = _load_single_plugin_instance(plugin_config)
    PLUGIN_CLASSES[plugin_id] = instance
    return instance
