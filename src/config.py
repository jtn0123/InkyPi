import functools
import hashlib
import importlib
import json
import logging
import os
import shutil
import tempfile
import threading
from typing import Any, cast

from dotenv import load_dotenv, set_key, unset_key

from model import PlaylistManager, RefreshInfo

# Optional dependency: jsonschema for validating device.json (loaded dynamically to avoid typing issues)
jsonschema: Any = None
try:
    jsonschema = importlib.import_module("jsonschema")
except Exception:  # pragma: no cover
    jsonschema = None

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=4)
def _load_json_schema(schema_path: str) -> dict[str, Any]:
    """Load and cache a JSON Schema from disk.

    Cached by absolute schema path to avoid repeated disk I/O and parsing.
    """
    with open(schema_path) as f:
        return cast(dict[str, Any], json.load(f))


class Config:
    # Base path for the project directory
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

    # File paths relative to the script's directory (default; can be overridden)
    config_file = os.path.join(BASE_DIR, "config", "device.json")

    # File path for storing the current image being displayed
    current_image_file = os.path.join(BASE_DIR, "static", "images", "current_image.png")

    # File path for storing the processed image actually sent to the device
    processed_image_file = os.path.join(
        BASE_DIR, "static", "images", "processed_image.png"
    )

    # Directory path for storing plugin instance images
    plugin_image_dir = os.path.join(BASE_DIR, "static", "images", "plugins")

    # Directory path for storing historical processed images
    history_image_dir = os.path.join(BASE_DIR, "static", "images", "history")

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
        runtime_dir = (os.getenv("INKYPI_RUNTIME_DIR") or "").strip()
        if not runtime_dir:
            self.current_image_file = type(self).current_image_file
            self.processed_image_file = type(self).processed_image_file
            self.plugin_image_dir = type(self).plugin_image_dir
            self.history_image_dir = type(self).history_image_dir
            return

        runtime_images_dir = os.path.join(runtime_dir, "images")
        self.current_image_file = os.path.join(runtime_images_dir, "current_image.png")
        self.processed_image_file = os.path.join(
            runtime_images_dir, "processed_image.png"
        )
        self.plugin_image_dir = os.path.join(runtime_images_dir, "plugins")
        self.history_image_dir = os.path.join(runtime_images_dir, "history")

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
        prod_path = os.path.join(config_dir, "device.json")
        dev_path = os.path.join(config_dir, "device_dev.json")

        # 1) Explicit file from environment
        env_file = os.getenv("INKYPI_CONFIG_FILE")
        if env_file and os.path.isfile(env_file):
            logger.info(
                "config_loaded: Using config from INKYPI_CONFIG_FILE",
                extra={"source": "env", "path": env_file},
            )
            return env_file

        # 2) Respect class attribute override (possibly set by CLI)
        class_override = getattr(type(self), "config_file", None)
        if class_override and os.path.isfile(class_override):
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
            os.path.join(base_dir, "..", "install", "config_base", "device.json")
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
            )

    def read_config(self):
        """Reads the device config JSON file and returns it as a dictionary."""
        logger.debug(f"Reading device config from {self.config_file}")
        with open(self.config_file) as f:
            config = json.load(f)

        # Validate against JSON Schema if available
        self._validate_device_config(config)

        # Log a sanitized summary instead of full config to avoid leaking secrets
        try:
            logger.debug(
                "Loaded config (sanitized):\n%s",
                json.dumps(self._sanitize_config_for_log(config), indent=3),
            )
        except Exception:
            # Never break startup due to logging
            logger.debug("Loaded config (sanitized): <unavailable>")

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
            content_hash = hashlib.md5(serialized.encode()).hexdigest()
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
        return self.config

    def get_plugins(self):
        """Returns the list of plugin configurations, sorted by custom order if set."""
        plugin_order = self.config.get('plugin_order', [])

        if not plugin_order:
            return self.plugins_list

        # Create a dict for quick lookup
        plugins_dict = {p['id']: p for p in self.plugins_list}

        # Build ordered list
        ordered = []
        for plugin_id in plugin_order:
            if not isinstance(plugin_id, str):
                logger.warning("Skipping invalid plugin_order entry (non-string): %r", plugin_id)
                continue
            if plugin_id in plugins_dict:
                ordered.append(plugins_dict.pop(plugin_id))

        # Append any remaining plugins not in the order (new plugins)
        ordered.extend(plugins_dict.values())

        return ordered

    def set_plugin_order(self, order):
        """Sets the custom plugin display order."""
        self.update_value('plugin_order', order, write=True)

    def get_plugin(self, plugin_id):
        """Finds and returns a plugin config by its ID."""
        return next(
            (plugin for plugin in self.plugins_list if plugin["id"] == plugin_id), None
        )

    def get_resolution(self):
        """Returns the display resolution as a tuple (width, height) from the configuration."""
        resolution = self.get_config("resolution")
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
            except Exception as e:
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
        """Loads the refresh information from the config."""
        data = self.get_config("refresh_info", {}) or {}
        try:
            required = {"refresh_type", "plugin_id", "refresh_time", "image_hash"}
            if not isinstance(data, dict) or not required.issubset(data.keys()):
                raise ValueError("refresh_info missing required keys")
            return RefreshInfo.from_dict(data)
        except (KeyError, TypeError, ValueError) as e:
            logger.warning("Invalid refresh_info in config, using defaults: %s", e)
            return RefreshInfo("Manual Update", "", None, None)

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

    def _schema_dir(self):
        """Return absolute path to the config schemas directory."""
        return os.path.join(self.BASE_DIR, "config", "schemas")

    def _validate_device_config(self, config: dict):
        """Validate device.json against the bundled JSON Schema.

        Uses draft 2020-12. On schema violations, raises ValueError with a concise
        message including the failing path and (safely) the invalid value when helpful.
        If the validator or schema is unavailable, validation is skipped.
        """
        # First: fallback validation when jsonschema isn't available
        if jsonschema is None:
            # Only validate orientation if provided; schema does not require it
            if "orientation" in config:
                orientation = config.get("orientation")
                if orientation not in ("horizontal", "vertical"):
                    raise ValueError(
                        f"device.json failed schema validation: orientation: invalid value (got: {repr(orientation)})"
                    )
            # No further schema checks available; exit early
            return

        # jsonschema is available, proceed with full validation inside a try/except
        try:
            schema_path = os.path.join(self._schema_dir(), "device_config.schema.json")
            if not os.path.isfile(schema_path):
                logger.warning(
                    "Device config schema not found at %s; skipping validation",
                    schema_path,
                )
                return
            schema = _load_json_schema(schema_path)
            jsonschema.Draft202012Validator(schema).validate(config)
        except Exception as ex:
            # If this is a jsonschema ValidationError, wrap with user-friendly ValueError; else warn
            try:
                is_validation_error = (
                    jsonschema is not None
                    and hasattr(jsonschema, "exceptions")
                    and isinstance(ex, jsonschema.exceptions.ValidationError)
                )
            except Exception:
                is_validation_error = False
            if is_validation_error:
                ve = ex
                msg = getattr(ve, "message", str(ve))
                try:
                    if hasattr(ve, "path") and ve.path:
                        path = ".".join(str(p) for p in ve.path)
                        msg = f"{path}: {msg}"
                    bad = getattr(ve, "instance", None)
                    bad_repr = repr(bad)
                    if len(bad_repr) > 200:
                        bad_repr = bad_repr[:197] + "..."
                    msg = f"{msg} (got: {bad_repr})"
                except Exception:
                    pass
                raise ValueError(f"device.json failed schema validation: {msg}") from ex
            logger.warning(
                "device.json validation encountered a non-fatal error: %s", ex
            )

    @staticmethod
    def _sanitize_config_for_log(config_dict):
        """Return a sanitized copy of the config for logging.

        - Masks values for any keys that look secret-ish: contains one of
          ['secret', 'token', 'api', 'key', 'password'] (case-insensitive).
        - Replaces playlist plugin_settings with a summary to avoid leaking plugin
          credentials saved in settings.
        - Keeps non-sensitive high-level fields as-is for debuggability.
        """

        def _looks_sensitive(key_name: str) -> bool:
            lowered = key_name.lower()
            return any(
                s in lowered for s in ("secret", "token", "api", "key", "password")
            )

        def _mask(value):
            if isinstance(value, dict):
                return {
                    k: ("***" if _looks_sensitive(k) else _mask(v))
                    for k, v in value.items()
                }
            if isinstance(value, list):
                return [_mask(v) for v in value]
            # Do not attempt to log raw bytes or large strings; keep small scalars
            if isinstance(value, int | float | bool) or value is None:
                return value
            if isinstance(value, str):
                # Keep short benign strings; mask long ones
                return (
                    value
                    if len(value) <= 64 and not any(c in value for c in ("\n", "\r"))
                    else "***"
                )
            return "<omitted>"

        sanitized: dict[str, Any] = {}
        for key, value in (config_dict or {}).items():
            if key == "playlist_config" and isinstance(value, dict):
                playlists = (
                    value.get("playlists", [])
                    if isinstance(value.get("playlists"), list)
                    else []
                )
                sanitized_playlists = []
                for pl in playlists:
                    try:
                        pl_name = pl.get("name")
                        plugins = (
                            pl.get("plugins", [])
                            if isinstance(pl.get("plugins"), list)
                            else []
                        )
                        sanitized_playlists.append(
                            {
                                "name": pl_name,
                                "num_plugins": len(plugins),
                                # Do not expose per-plugin settings; only summarize ids/names
                                "plugins": [
                                    {
                                        "plugin_id": p.get("plugin_id"),
                                        "name": p.get("name"),
                                        "has_settings": bool(p.get("plugin_settings")),
                                    }
                                    for p in plugins
                                ],
                            }
                        )
                    except Exception:
                        sanitized_playlists.append(
                            {"name": "<unknown>", "num_plugins": 0}
                        )
                sanitized[key] = {
                    "active_playlist": value.get("active_playlist"),
                    "playlists": sanitized_playlists,
                }
            elif _looks_sensitive(key):
                sanitized[key] = "***"
            else:
                sanitized[key] = _mask(value)

        return sanitized
