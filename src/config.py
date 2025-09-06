import os
import json
import logging
import shutil
from dotenv import load_dotenv
from model import PlaylistManager, RefreshInfo

logger = logging.getLogger(__name__)

class Config:
    # Base path for the project directory
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

    # File paths relative to the script's directory (default; can be overridden)
    config_file = os.path.join(BASE_DIR, "config", "device.json")

    # File path for storing the current image being displayed
    current_image_file = os.path.join(BASE_DIR, "static", "images", "current_image.png")

    # Directory path for storing plugin instance images
    plugin_image_dir = os.path.join(BASE_DIR, "static", "images", "plugins")

    def __init__(self):
        # Resolve which config file to use (env/CLI overrides with safe fallbacks)
        self.config_file = self._determine_config_path()

        # Ensure output directories exist
        os.makedirs(os.path.dirname(self.current_image_file), exist_ok=True)
        os.makedirs(self.plugin_image_dir, exist_ok=True)

        self.config = self.read_config()
        self.plugins_list = self.read_plugins_list()
        self.playlist_manager = self.load_playlist_manager()
        self.refresh_info = self.load_refresh_info()

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
            logger.info(f"Using config file from INKYPI_CONFIG_FILE: {env_file}")
            return env_file

        # 2) Respect class attribute override (possibly set by CLI)
        class_override = getattr(type(self), "config_file", None)
        if class_override and os.path.isfile(class_override):
            logger.info(f"Using config file from class override: {class_override}")
            return class_override

        # 3) INKYPI_ENV hint
        env_mode = (os.getenv("INKYPI_ENV", "").strip() or os.getenv("FLASK_ENV", "").strip()).lower()
        if env_mode in ("dev", "development") and os.path.isfile(dev_path):
            logger.info(f"Using dev config due to INKYPI_ENV: {dev_path}")
            return dev_path

        # 4) Prefer prod if it exists
        if os.path.isfile(prod_path):
            logger.info(f"Using prod config: {prod_path}")
            return prod_path

        # 5) Fallback to dev if it exists
        if os.path.isfile(dev_path):
            logger.info(f"Using dev config (fallback): {dev_path}")
            return dev_path

        # 6) Bootstrap from template if neither exists
        template_path = os.path.abspath(os.path.join(base_dir, "..", "install", "config_base", "device.json"))
        try:
            os.makedirs(config_dir, exist_ok=True)
            shutil.copyfile(template_path, prod_path)
            logger.warning(
                "No config found. Bootstrapped a new device.json from template: %s",
                template_path,
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

        logger.debug("Loaded config:\n%s", json.dumps(config, indent=3))

        return config

    def read_plugins_list(self):
        """Reads the plugin-info.json config JSON from each plugin folder. Excludes the base plugin."""
        # Iterate over all plugin folders
        plugins_list = []
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
        """Updates the cached config from the model objects and writes to the config file."""
        logger.debug(f"Writing device config to {self.config_file}")
        self.update_value("playlist_config", self.playlist_manager.to_dict())
        self.update_value("refresh_info", self.refresh_info.to_dict())
        with open(self.config_file, 'w') as outfile:
            json.dump(self.config, outfile, indent=4)

    def get_config(self, key=None, default={}):
        """Gets the value of a specific configuration key or returns the entire config if none provided."""
        if key is not None:
            return self.config.get(key, default)
        return self.config

    def get_plugins(self):
        """Returns the list of plugin configurations."""
        return self.plugins_list

    def get_plugin(self, plugin_id):
        """Finds and returns a plugin config by its ID."""
        return next((plugin for plugin in self.plugins_list if plugin['id'] == plugin_id), None)

    def get_resolution(self):
        """Returns the display resolution as a tuple (width, height) from the configuration."""
        resolution = self.get_config("resolution")
        width, height = resolution
        return (int(width), int(height))

    def update_config(self, config):
        """Updates the config with the new values provided and writes to the config file."""
        self.config.update(config)
        self.write_config()

    def update_value(self, key, value, write=False):
        """Updates a specific key in the configuration with a new value and optionally writes it to the config file."""
        self.config[key] = value
        if write:
            self.write_config()

    def load_env_key(self, key):
        """Loads an environment variable using dotenv and returns its value."""
        load_dotenv(override=True)
        return os.getenv(key)

    def load_playlist_manager(self):
        """Loads the playlist manager object from the config."""
        playlist_manager = PlaylistManager.from_dict(self.get_config("playlist_config"))
        if not playlist_manager.playlists:
            playlist_manager.add_default_playlist()
        return playlist_manager

    def load_refresh_info(self):
        """Loads the refresh information from the config."""
        return RefreshInfo.from_dict(self.get_config("refresh_info"))

    def get_playlist_manager(self):
        """Returns the playlist manager."""
        return self.playlist_manager

    def get_refresh_info(self):
        """Returns the refresh information."""
        return self.refresh_info
