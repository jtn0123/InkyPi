# app_registry.py

import importlib
import json
import logging
import os
import sys
import threading
from pathlib import Path

from utils.app_utils import resolve_path

logger = logging.getLogger("plugins.plugin_registry")
PLUGINS_DIR = "plugins"
PLUGIN_CLASSES = {}
_PLUGIN_CONFIGS = {}
_registry_lock = threading.RLock()
_LAST_HOT_RELOAD: dict | None = None
_hot_reload_lock = threading.Lock()


def _is_dev_mode() -> bool:
    env_mode = (
        os.getenv("INKYPI_ENV", "").strip() or os.getenv("FLASK_ENV", "").strip()
    ).lower()
    # When running tests, prefer stable import behavior so monkeypatch/patch works reliably
    if os.getenv("PYTEST_CURRENT_TEST"):
        return False
    return env_mode in ("dev", "development")


def _load_single_plugin_instance(plugin_config):
    plugin_id = plugin_config.get("id")
    module_name = f"plugins.{plugin_id}.{plugin_id}"
    try:
        reloaded = False
        no_hot_reload = os.getenv("INKYPI_NO_HOT_RELOAD", "").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        if _is_dev_mode() and module_name in sys.modules and not no_hot_reload:
            logger.info(f"Hot reloading plugin module {module_name}")
            module = importlib.reload(sys.modules[module_name])
            reloaded = True
        else:
            module = importlib.import_module(module_name)
        plugin_cls = getattr(module, plugin_config.get("class"), None)
        if not plugin_cls:
            raise ImportError(
                f"Class '{plugin_config.get('class')}' not found in module {module_name}"
            )
        instance = plugin_cls(plugin_config)
        # record hot reload info for request/response hooks to surface
        global _LAST_HOT_RELOAD
        with _hot_reload_lock:
            _LAST_HOT_RELOAD = {"plugin_id": plugin_id, "reloaded": reloaded}
        return instance
    except ImportError as e:
        logger.error(f"Failed to import plugin module {module_name}: {e}")
        raise


def _check_plugin_version(
    plugin_id: str, plugin_dir: Path
) -> tuple[str | None, str | None]:
    """Read api_version and version from a plugin's plugin-info.json.

    Returns (api_version, version). Missing fields are returned as None and
    logged at DEBUG level for backward compatibility.
    """
    from plugins.base_plugin.base_plugin import PLUGIN_API_VERSION

    info_path = plugin_dir / "plugin-info.json"
    api_version = None
    version = None
    if info_path.is_file():
        try:
            with open(info_path, encoding="utf-8") as f:
                info = json.load(f)
            api_version = info.get("api_version")
            version = info.get("version")
        except Exception as e:
            logger.debug("Could not read plugin-info.json for '%s': %s", plugin_id, e)

    if api_version is None:
        logger.debug(
            "Plugin '%s' has no api_version in plugin-info.json (backward compatible).",
            plugin_id,
        )
    else:
        try:
            declared_major = int(str(api_version).split(".")[0])
            current_major = int(str(PLUGIN_API_VERSION).split(".")[0])
            if declared_major != current_major:
                logger.warning(
                    "Plugin '%s' declares api_version '%s' but loader expects '%s'. "
                    "Major version mismatch — plugin will still be loaded.",
                    plugin_id,
                    api_version,
                    PLUGIN_API_VERSION,
                )
        except (ValueError, IndexError) as e:
            logger.warning(
                "Plugin '%s' has unparseable api_version '%s': %s",
                plugin_id,
                api_version,
                e,
            )

    if version is None:
        logger.debug(
            "Plugin '%s' has no version in plugin-info.json (backward compatible).",
            plugin_id,
        )

    return api_version, version


def load_plugins(plugins_config):
    """Validate plugin directories and register configs for lazy loading.

    Plugin modules are not imported until first use via get_plugin_instance(),
    reducing startup memory and time on low-resource devices.
    """
    plugins_module_path = Path(resolve_path(PLUGINS_DIR))
    for plugin in plugins_config:
        plugin_id = plugin.get("id")
        if plugin.get("disabled", False):
            logger.info(f"Plugin {plugin_id} is disabled, skipping.")
            continue

        plugin_dir = plugins_module_path / plugin_id
        if not plugin_dir.is_dir():
            logger.error(
                "Could not find plugin directory %s for '%s', skipping.",
                plugin_dir,
                plugin_id,
            )
            continue

        module_path = plugin_dir / f"{plugin_id}.py"
        if not module_path.is_file():
            logger.error(
                "Could not find module path %s for '%s', skipping.",
                module_path,
                plugin_id,
            )
            continue

        # Read version metadata from plugin-info.json and expose on config
        api_version, version = _check_plugin_version(plugin_id, plugin_dir)
        plugin = dict(plugin)
        if api_version is not None:
            plugin.setdefault("api_version", api_version)
        if version is not None:
            plugin.setdefault("version", version)

        # Store config for lazy loading; actual import deferred to get_plugin_instance()
        with _registry_lock:
            _PLUGIN_CONFIGS[plugin_id] = plugin
        logger.debug(f"Registered plugin '{plugin_id}' for lazy loading")


def get_plugin_instance(plugin_config):
    plugin_id = plugin_config.get("id")

    # In dev mode, always (re)load and re-instantiate to pick up code changes.
    if _is_dev_mode():
        return _load_single_plugin_instance(plugin_config)

    with _registry_lock:
        # Retrieve cached instance if available
        instance = PLUGIN_CLASSES.get(plugin_id)
        stored_config = _PLUGIN_CONFIGS.get(plugin_id)
    if instance:
        return instance

    # Lazy load: import and cache on first use
    if stored_config:
        instance = _load_single_plugin_instance(stored_config)
        with _registry_lock:
            PLUGIN_CLASSES[plugin_id] = instance
        return instance

    raise ValueError(f"Plugin '{plugin_id}' is not registered.")


def reset_plugin_registry():
    """Clear plugin loader caches/config registration (test isolation helper)."""
    with _registry_lock:
        PLUGIN_CLASSES.clear()
        _PLUGIN_CONFIGS.clear()


def get_registered_plugin_ids():
    """Return the set of plugin IDs that are registered (loaded or pending lazy load)."""
    with _registry_lock:
        return set(PLUGIN_CLASSES) | set(_PLUGIN_CONFIGS)


def pop_hot_reload_info():
    """Return and clear the last hot reload info recorded by the loader.

    Returns a dict like {"plugin_id": str, "reloaded": bool} or None.
    """
    global _LAST_HOT_RELOAD
    with _hot_reload_lock:
        info = _LAST_HOT_RELOAD
        _LAST_HOT_RELOAD = None
    return info
