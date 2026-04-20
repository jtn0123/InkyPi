import hashlib
import json
import logging
import os
import shutil
import tempfile
import threading
from collections.abc import Callable
from typing import Any

from dotenv import load_dotenv, set_key, unset_key

from model import PlaylistManager
from utils.config_schema import validate_device_config
from utils.paths import (
    BASE_DIR as _PATHS_BASE_DIR,
    CURRENT_IMAGE_FILE as _DEFAULT_CURRENT_IMAGE,
    HISTORY_IMAGE_DIR as _DEFAULT_HISTORY_DIR,
    PLUGIN_IMAGE_DIR as _DEFAULT_PLUGIN_DIR,
    PROCESSED_IMAGE_FILE as _DEFAULT_PROCESSED_IMAGE,
    resolve_runtime_paths,
)
from utils.refresh_info import RefreshInfoRepository

logger = logging.getLogger(__name__)

_DEVICE_JSON = "device.json"

# JTN-777: mirror the 64-character cap enforced by /save_settings
# (see blueprints/settings/_config.py::_DEVICE_NAME_MAX_LEN — JTN-746).
# Legacy device.local.json files edited before the cap existed can still
# contain names longer than 64 chars. Those values would otherwise leak
# unbounded into <title>, title=, and alt= render sites (where CSS cannot
# truncate). Coerce at config-load time so every consumer — templates,
# screen readers, tab titles — sees a sane value.
_DEVICE_NAME_MAX_LEN = 64

_SENSITIVE_TERMS = ("secret", "token", "api", "key", "password")


def _looks_sensitive(key_name: str) -> bool:
    """Return True if the key name suggests it may hold a secret value."""
    lowered = key_name.lower()
    return any(s in lowered for s in _SENSITIVE_TERMS)


def _mask_config_value(value: Any) -> Any:
    """Recursively mask sensitive values for safe logging."""
    if isinstance(value, dict):
        return {
            k: ("***" if _looks_sensitive(k) else _mask_config_value(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_mask_config_value(v) for v in value]
    if isinstance(value, int | float | bool) or value is None:
        return value
    if isinstance(value, str):
        # Keep short benign strings; mask long or multi-line ones
        return (
            value
            if len(value) <= 64 and not any(c in value for c in ("\n", "\r"))
            else "***"
        )
    return "<omitted>"


def _coerce_device_name(config: dict) -> bool:
    """Truncate ``config['name']`` to ``_DEVICE_NAME_MAX_LEN`` characters in place.

    Returns True if the name was modified (over-length or non-string coerced
    to empty). Logs a warning on truncation so operators know the stored value
    exceeded the render-safe cap.

    The on-disk config is not rewritten here; callers that subsequently invoke
    :meth:`Config.write_config` will flush the coerced value naturally. The
    original value is preserved on disk until that happens.
    """
    name = config.get("name")
    if not isinstance(name, str):
        # JSON schema allows any string, and the validator has already run.
        # Non-strings shouldn't reach here, but be defensive.
        return False
    if len(name) <= _DEVICE_NAME_MAX_LEN:
        return False
    truncated = name[:_DEVICE_NAME_MAX_LEN]
    logger.warning(
        "device_name_truncated: stored name is %d chars; truncating to %d "
        "(JTN-777). Re-save settings to persist the coerced value.",
        len(name),
        _DEVICE_NAME_MAX_LEN,
    )
    config["name"] = truncated
    return True


def _summarize_playlist(pl: Any) -> dict:
    """Summarize a single playlist entry, stripping per-plugin settings."""
    try:
        plugins = pl.get("plugins", []) if isinstance(pl.get("plugins"), list) else []
        return {
            "name": pl.get("name"),
            "num_plugins": len(plugins),
            "plugins": [
                {
                    "plugin_id": p.get("plugin_id"),
                    "name": p.get("name"),
                    "has_settings": bool(p.get("plugin_settings")),
                }
                for p in plugins
            ],
        }
    except Exception:
        return {"name": "<unknown>", "num_plugins": 0}


class Config:
    # Base path for the project directory — canonical source is utils.paths
    BASE_DIR = _PATHS_BASE_DIR

    # File paths relative to the script's directory (default; can be overridden)
    config_file = os.path.join(BASE_DIR, "config", _DEVICE_JSON)

    # Image paths — canonical defaults live in utils.paths; kept as class
    # attributes for backward compatibility (worker.py sets them on the class
    # before constructing a child-process Config).
    current_image_file = _DEFAULT_CURRENT_IMAGE
    processed_image_file = _DEFAULT_PROCESSED_IMAGE
    plugin_image_dir = _DEFAULT_PLUGIN_DIR
    history_image_dir = _DEFAULT_HISTORY_DIR

    def __getstate__(self):
        """Support pickling by excluding the unpicklable RLock.

        This is required on Linux where multiprocessing uses the 'spawn' or
        'forkserver' start method, which pickles objects passed to child
        processes.
        """
        state = self.__dict__.copy()
        state.pop("_config_lock", None)
        return state

    def __setstate__(self, state):
        """Restore the RLock when unpickling."""
        self.__dict__.update(state)
        self._config_lock = threading.RLock()

    def __init__(self):
        self._config_lock = threading.RLock()
        self._last_written_hash = None
        # mtime-based read cache: skip JSON parse + schema validation when the
        # file has not changed.  Stored as (mtime_ns: int, data: dict).
        self._config_cache_mtime: int | None = None
        self._config_cache_data: dict | None = None
        self._resolve_runtime_paths()
        # Resolve which config file to use (env/CLI overrides with safe fallbacks)
        self.config_file = self._determine_config_path()

        # Ensure output directories exist
        os.makedirs(os.path.dirname(self.current_image_file), exist_ok=True)
        os.makedirs(os.path.dirname(self.processed_image_file), exist_ok=True)
        os.makedirs(self.plugin_image_dir, exist_ok=True)
        os.makedirs(self.history_image_dir, exist_ok=True)

        # Ensure a preview image exists so the web UI's /preview route works
        try:
            default_img = os.path.join(self.BASE_DIR, "static", "images", "inkypi.png")
            if not os.path.exists(self.processed_image_file):
                shutil.copyfile(default_img, self.processed_image_file)
            if not os.path.exists(self.current_image_file):
                shutil.copyfile(self.processed_image_file, self.current_image_file)
        except OSError as e:
            logger.warning("Could not initialize preview images: %s", e)

        self.config = self.read_config()
        self.plugins_list = self.read_plugins_list()
        self.playlist_manager = self.load_playlist_manager()
        self.refresh_info = self.load_refresh_info()

    def _resolve_runtime_paths(self):
        runtime_dir = (os.getenv("INKYPI_RUNTIME_DIR") or "").strip() or None
        if not runtime_dir:
            # No runtime override — use class-level defaults (may have been
            # overridden by worker.py before construction).
            self.current_image_file = type(self).current_image_file
            self.processed_image_file = type(self).processed_image_file
            self.plugin_image_dir = type(self).plugin_image_dir
            self.history_image_dir = type(self).history_image_dir
            return

        paths = resolve_runtime_paths(runtime_dir)
        self.current_image_file = paths["current_image_file"]
        self.processed_image_file = paths["processed_image_file"]
        self.plugin_image_dir = paths["plugin_image_dir"]
        self.history_image_dir = paths["history_image_dir"]

    def _determine_config_path(self):
        """Determine which device config file to load.

        Precedence:
        1. INKYPI_CONFIG_FILE env var if it exists
        2. Explicit class attribute override (e.g., set by CLI) if it exists
        3. INKYPI_ENV=dev implies device_dev.json if present
        4. device.json if present
        5. device_dev.json if present
        6. Bootstrap device.json from install/config_base/device.json
        """
        base_dir = self.BASE_DIR
        config_dir = os.path.join(base_dir, "config")
        prod_path = os.path.join(config_dir, _DEVICE_JSON)
        dev_path = os.path.join(config_dir, "device_dev.json")

        # 1) Explicit file from environment
        env_file = os.getenv("INKYPI_CONFIG_FILE")
        if env_file and os.path.isfile(env_file):
            logger.info(
                "config_loaded: Using config from INKYPI_CONFIG_FILE",
                extra={"source": "env", "path": env_file},
            )
            return env_file

        # 2) Respect class attribute override (e.g. set by CLI or a subclass), but only
        # when it differs from the built-in default.  The base Config class always has
        # config_file set to the production device.json path; if that value is still the
        # default it means nobody has explicitly overridden it, so we must fall through to
        # the INKYPI_ENV check (step 3).  Only treat config_file as an explicit override
        # when it has been changed from the original default (e.g. by CLI or a subclass).
        _base_default = os.path.join(base_dir, "config", _DEVICE_JSON)
        class_override = getattr(type(self), "config_file", None)
        if (
            class_override is not None
            and class_override != _base_default
            and os.path.isfile(class_override)
        ):
            logger.info(
                "config_loaded: Using config from class override",
                extra={"source": "class_override", "path": class_override},
            )
            return class_override

        # 3) INKYPI_ENV hint
        env_mode = (
            os.getenv("INKYPI_ENV", "").strip() or os.getenv("FLASK_ENV", "").strip()
        ).lower()
        if env_mode in ("dev", "development") and os.path.isfile(dev_path):
            logger.info(
                "config_loaded: Using dev config due to INKYPI_ENV",
                extra={"source": "env_mode", "path": dev_path, "mode": env_mode},
            )
            return dev_path

        # 4) Prefer prod if it exists
        if os.path.isfile(prod_path):
            logger.info(
                "config_loaded: Using prod config",
                extra={"source": "file", "path": prod_path},
            )
            return prod_path

        # 5) Fallback to dev if it exists
        if os.path.isfile(dev_path):
            logger.info(
                "config_loaded: Using dev config as fallback",
                extra={"source": "fallback", "path": dev_path},
            )
            return dev_path

        # 6) Bootstrap from template if neither exists
        template_path = os.path.abspath(
            os.path.join(base_dir, "..", "install", "config_base", _DEVICE_JSON)
        )
        try:
            os.makedirs(config_dir, exist_ok=True)
            shutil.copyfile(template_path, prod_path)
            logger.warning(
                "config_loaded: Bootstrapped new device.json from template",
                extra={
                    "source": "bootstrap",
                    "path": prod_path,
                    "template": template_path,
                },
            )
            return prod_path
        except Exception as ex:
            raise RuntimeError(
                f"Unable to locate or create a device configuration file. Checked: "
                f"env INKYPI_CONFIG_FILE, class override, {prod_path}, {dev_path}. "
                f"Also attempted bootstrap from {template_path} and failed: {ex}"
            ) from ex

    def invalidate_config_cache(self) -> None:
        """Invalidate the in-memory config read cache.

        The next call to :meth:`read_config` will re-stat the file and, if the
        mtime has changed, re-parse and re-validate the JSON.  Call this after
        any external write to the config file that bypasses :meth:`write_config`.
        """
        with self._config_lock:
            self._config_cache_mtime = None
            self._config_cache_data = None

    def read_config(self) -> dict:
        """Reads the device config JSON file and returns it as a dictionary.

        Uses an mtime-based in-memory cache so that repeated calls skip the
        JSON parse and jsonschema validation when the file has not changed on
        disk.  The stat call (to read mtime) is always performed, but it is
        ~100x cheaper than a full parse+validate cycle.

        Thread safety: the cache is protected by ``_config_lock``.
        """
        with self._config_lock:
            try:
                stat = os.stat(self.config_file)
                current_mtime_ns = stat.st_mtime_ns
            except OSError:
                # File is gone or unreadable — clear cache and let the open()
                # below raise a clear error.
                self._config_cache_mtime = None
                self._config_cache_data = None
                current_mtime_ns = None

            if (
                current_mtime_ns is not None
                and self._config_cache_mtime is not None
                and current_mtime_ns == self._config_cache_mtime
                and self._config_cache_data is not None
            ):
                logger.debug(
                    "Config cache hit (mtime_ns=%s): skipping parse+validate",
                    current_mtime_ns,
                )
                return self._config_cache_data.copy()

            logger.debug("Reading device config from %s", self.config_file)
            with open(self.config_file) as f:
                config = json.load(f)

            # Validate against JSON Schema — raises ConfigValidationError on failure
            validate_device_config(config)

            # JTN-777: coerce oversize legacy device names to the same 64-char
            # cap enforced by /save_settings. Done after schema validation so
            # the cap applies even if a user edited device.local.json directly.
            _coerce_device_name(config)

            # Log a sanitized summary instead of full config to avoid leaking secrets
            try:
                logger.debug(
                    "Loaded config (sanitized):\n%s",
                    json.dumps(self._sanitize_config_for_log(config), indent=3),
                )
            except Exception:
                # Never break startup due to logging
                logger.debug("Loaded config (sanitized): <unavailable>")

            # Update cache after successful parse+validate
            self._config_cache_mtime = current_mtime_ns
            self._config_cache_data = config

            return config

    def read_plugins_list(self):
        """Reads the plugin-info.json config JSON from each plugin folder. Excludes the base plugin."""
        # Iterate over all plugin folders
        plugins_list: list[dict] = []
        plugins_root = os.path.join(self.BASE_DIR, "plugins")
        if not os.path.isdir(plugins_root):
            return plugins_list
        for plugin in sorted(os.listdir(plugins_root)):
            plugin_path = os.path.join(plugins_root, plugin)
            if os.path.isdir(plugin_path) and plugin != "__pycache__":
                # Check if the plugin-info.json file exists
                plugin_info_file = os.path.join(plugin_path, "plugin-info.json")
                if os.path.isfile(plugin_info_file):
                    logger.debug(f"Reading plugin info from {plugin_info_file}")
                    with open(plugin_info_file) as f:
                        plugin_info = json.load(f)
                    plugins_list.append(plugin_info)

        return plugins_list

    def write_config(self):
        """Updates the cached config from the model objects and writes to the config file.

        Skips the disk write when the serialized content is identical to the
        last write, reducing SD-card wear on low-power devices.
        """
        with self._config_lock:
            self.config["playlist_config"] = self.playlist_manager.to_dict()
            self.config["refresh_info"] = self.refresh_info.to_dict()
            serialized = json.dumps(self.config, indent=4)
            content_hash = hashlib.sha256(serialized.encode()).hexdigest()
            if content_hash == self._last_written_hash:
                logger.debug("Config unchanged, skipping write")
                return
            logger.debug(f"Writing device config to {self.config_file}")
            config_dir = os.path.dirname(self.config_file) or "."
            fd, tmp_path = tempfile.mkstemp(
                dir=config_dir,
                prefix=".device.",
                suffix=".tmp",
            )
            try:
                with os.fdopen(fd, "w") as outfile:
                    outfile.write(serialized)
                    outfile.flush()
                    os.fsync(outfile.fileno())
                os.replace(tmp_path, self.config_file)
                self._last_written_hash = content_hash
                # Refresh the read cache so the next read_config() call sees the
                # newly written content without re-parsing.  We stat() after the
                # replace so the recorded mtime is the actual on-disk mtime.
                try:
                    new_mtime_ns = os.stat(self.config_file).st_mtime_ns
                    self._config_cache_mtime = new_mtime_ns
                    self._config_cache_data = self.config.copy()
                except OSError:
                    # Non-fatal: cache will be rebuilt on the next read_config().
                    self._config_cache_mtime = None
                    self._config_cache_data = None
            finally:
                try:
                    if os.path.exists(tmp_path):
                        os.unlink(tmp_path)
                except OSError:
                    pass

    def get_config(self, key=None, default=None):
        """Gets the value of a specific configuration key or returns the entire config if none provided.

        If the key is absent and no default is supplied, ``None`` is returned.
        """
        if key is not None:
            return self.config.get(key, default)
        return self.config.copy()

    def get_plugins(self):
        """Returns the list of plugin configurations, sorted by custom order if set."""
        plugin_order = self.config.get("plugin_order", [])

        if not plugin_order:
            return self.plugins_list

        # Create a dict for quick lookup
        plugins_dict = {p["id"]: p for p in self.plugins_list}

        # Build ordered list
        ordered = []
        for plugin_id in plugin_order:
            if not isinstance(plugin_id, str):
                logger.warning(
                    "Skipping invalid plugin_order entry (non-string): %r", plugin_id
                )
                continue
            if plugin_id in plugins_dict:
                ordered.append(plugins_dict.pop(plugin_id))

        # Append any remaining plugins not in the order (new plugins)
        ordered.extend(plugins_dict.values())

        return ordered

    def set_plugin_order(self, order):
        """Sets the custom plugin display order."""
        self.update_value("plugin_order", order, write=True)

    def get_plugin(self, plugin_id):
        """Finds and returns a plugin config by its ID."""
        return next(
            (plugin for plugin in self.plugins_list if plugin["id"] == plugin_id), None
        )

    def get_resolution(self):
        """Returns the display resolution as a tuple (width, height) from the configuration."""
        resolution = self.get_config("resolution", default=[800, 480])
        width, height = resolution
        return (int(width), int(height))

    def update_config(self, config):
        """Updates the config with the new values provided and writes to the config file."""
        with self._config_lock:
            self.config.update(config)
            self.write_config()

    def update_value(self, key, value, write=False):
        """Updates a specific key in the configuration with a new value and optionally writes it to the config file."""
        with self._config_lock:
            self.config[key] = value
            if write:
                self.write_config()

    def update_atomic(self, update_fn: Callable[[dict], None]) -> None:
        """Run update_fn(self._config) while holding the config lock and atomically write.

        This ensures the full read-modify-write cycle is performed under the
        config lock, preventing concurrent threads from clobbering each other's
        changes.  Because ``_config_lock`` is a reentrant lock, methods that
        already hold it (e.g. ``write_config``) are safe to call from within
        ``update_fn``.
        """
        with self._config_lock:
            update_fn(self.config)
            self.write_config()

    def get_env_file_path(self):
        """Return absolute path to the .env file used for secrets.

        Precedence:
        - PROJECT_DIR environment variable if provided (set in production by install script)
        - Repository root inferred as parent of src directory
        """
        project_dir = os.getenv("PROJECT_DIR")
        if not project_dir:
            # default to repo root: parent of src
            project_dir = os.path.abspath(os.path.join(self.BASE_DIR, ".."))
        return os.path.join(project_dir, ".env")

    def load_env_key(self, key):
        """Loads an environment variable from the managed .env and returns its value."""
        load_dotenv(dotenv_path=self.get_env_file_path(), override=True)
        return os.getenv(key)

    def set_env_key(self, key, value):
        """Safely set/update a key in the managed .env file and current process env."""
        env_path = self.get_env_file_path()
        # Ensure directory exists and file is present with safe permissions
        os.makedirs(os.path.dirname(env_path), exist_ok=True)
        if not os.path.exists(env_path):
            with open(env_path, "a"):
                pass  # Create empty file
            try:
                os.chmod(env_path, 0o600)
            except OSError as e:
                logger.warning("Could not set .env file permissions to 0600: %s", e)
        # Write without quotes to satisfy tests and common .env style
        try:
            set_key(env_path, key, value, quote_mode="never")
        except TypeError:
            # Older dotenv versions: fallback to manual append/update
            # Read existing lines and replace or append
            lines = []
            if os.path.exists(env_path):
                with open(env_path) as f:
                    lines = f.read().splitlines()
            key_prefix = f"{key}="
            updated = False
            for i, line in enumerate(lines):
                if line.startswith(key_prefix):
                    lines[i] = f"{key}={value}"
                    updated = True
                    break
            if not updated:
                lines.append(f"{key}={value}")
            with open(env_path, "w") as f:
                f.write("\n".join(lines) + "\n")
        os.environ[key] = value
        return True

    def unset_env_key(self, key):
        """Remove a key from the managed .env file and current process env."""
        env_path = self.get_env_file_path()
        if os.path.exists(env_path):
            try:
                unset_key(env_path, key)
            except Exception as e:
                logger.warning("Failed to unset env key %s: %s", key, e)
        os.environ.pop(key, None)
        return True

    def load_playlist_manager(self):
        """Loads the playlist manager object from the config."""
        playlist_manager = PlaylistManager.from_dict(
            self.get_config("playlist_config", {})
        )
        if not playlist_manager.playlists:
            playlist_manager.add_default_playlist()
        return playlist_manager

    def load_refresh_info(self):
        """Loads the refresh information from the config.

        Delegates to :class:`~utils.refresh_info.RefreshInfoRepository`.
        """
        data = self.get_config("refresh_info", {}) or {}
        self._refresh_info_repo = RefreshInfoRepository(data)
        return self._refresh_info_repo.get()

    def get_playlist_manager(self):
        """Returns the playlist manager."""
        return self.playlist_manager

    def get_refresh_info(self):
        """Returns the refresh information."""
        return self.refresh_info

    def get_plugin_image_path(self, plugin_id, instance_name):
        """Returns the full path for a plugin instance's image file."""
        from model import PluginInstance

        # Create a temporary plugin instance to get the image path
        plugin_instance = PluginInstance(plugin_id, instance_name, {}, {})
        return os.path.join(self.plugin_image_dir, plugin_instance.get_image_path())

    @staticmethod
    def _sanitize_config_for_log(config_dict):
        """Return a sanitized copy of the config for logging.

        - Masks values for any keys that look secret-ish: contains one of
          ['secret', 'token', 'api', 'key', 'password'] (case-insensitive).
        - Replaces playlist plugin_settings with a summary to avoid leaking plugin
          credentials saved in settings.
        - Keeps non-sensitive high-level fields as-is for debuggability.
        """
        sanitized: dict[str, Any] = {}
        for key, value in (config_dict or {}).items():
            if key == "playlist_config" and isinstance(value, dict):
                playlists = (
                    value.get("playlists", [])
                    if isinstance(value.get("playlists"), list)
                    else []
                )
                sanitized[key] = {
                    "active_playlist": value.get("active_playlist"),
                    "playlists": [_summarize_playlist(pl) for pl in playlists],
                }
            elif _looks_sensitive(key):
                sanitized[key] = "***"
            else:
                sanitized[key] = _mask_config_value(value)
        return sanitized
