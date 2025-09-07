import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class RefreshInfo:
    """Keeps track of refresh metadata.

    Attributes:
        refresh_time (str): ISO-formatted time string of the refresh.
        image_hash (int): SHA-256 hash of the image.
        refresh_type (str): Refresh type ['Manual Update', 'Playlist'].
        plugin_id (str): Plugin id of the refresh.
        playlist (str): Playlist name if refresh_type is 'Playlist'.
        plugin_instance (str): Plugin instance name if refresh_type is 'Playlist'.
        plugin_meta (dict | None): Optional plugin-specific metadata for the latest refresh.
    """

    def __init__(
        self,
        refresh_type,
        plugin_id,
        refresh_time,
        image_hash,
        playlist=None,
        plugin_instance=None,
        # Optional performance metrics
        request_ms: int | None = None,
        display_ms: int | None = None,
        generate_ms: int | None = None,
        preprocess_ms: int | None = None,
        used_cached: bool | None = None,
        # Optional plugin-specific metadata
        plugin_meta: dict | None = None,
    ):
        """Initialize RefreshInfo instance."""
        self.refresh_time = refresh_time
        self.image_hash = image_hash
        self.refresh_type = refresh_type
        self.plugin_id = plugin_id
        self.playlist = playlist
        self.plugin_instance = plugin_instance
        # Optional metrics
        self.request_ms = request_ms
        self.display_ms = display_ms
        self.generate_ms = generate_ms
        self.preprocess_ms = preprocess_ms
        self.used_cached = used_cached
        # Optional plugin-specific metadata (e.g., WPOTD date/description)
        self.plugin_meta = plugin_meta

    def get_refresh_datetime(self):
        """Returns the refresh time as a datetime object or None if not set."""
        latest_refresh = None
        if self.refresh_time:
            latest_refresh = datetime.fromisoformat(self.refresh_time)
        return latest_refresh

    def to_dict(self):
        refresh_dict = {
            "refresh_time": self.refresh_time,
            "image_hash": self.image_hash,
            "refresh_type": self.refresh_type,
            "plugin_id": self.plugin_id,
        }
        if self.playlist:
            refresh_dict["playlist"] = self.playlist
        if self.plugin_instance:
            refresh_dict["plugin_instance"] = self.plugin_instance
        # Include optional metrics if available
        if self.request_ms is not None:
            refresh_dict["request_ms"] = self.request_ms
        if self.display_ms is not None:
            refresh_dict["display_ms"] = self.display_ms
        if self.generate_ms is not None:
            refresh_dict["generate_ms"] = self.generate_ms
        if self.preprocess_ms is not None:
            refresh_dict["preprocess_ms"] = self.preprocess_ms
        if self.used_cached is not None:
            refresh_dict["used_cached"] = self.used_cached
        # Include optional plugin metadata if available
        if getattr(self, "plugin_meta", None) is not None:
            refresh_dict["plugin_meta"] = self.plugin_meta
        return refresh_dict

    @classmethod
    def from_dict(cls, data):
        return cls(
            refresh_time=data.get("refresh_time"),
            image_hash=data.get("image_hash"),
            refresh_type=data.get("refresh_type"),
            plugin_id=data.get("plugin_id"),
            playlist=data.get("playlist"),
            plugin_instance=data.get("plugin_instance"),
            request_ms=data.get("request_ms"),
            display_ms=data.get("display_ms"),
            generate_ms=data.get("generate_ms"),
            preprocess_ms=data.get("preprocess_ms"),
            used_cached=data.get("used_cached"),
            plugin_meta=data.get("plugin_meta"),
        )


class PlaylistManager:
    """A class managing multiple time-based playlists.

    Attributes:
        playlists (list): A list of Playlist instances managed by the manager.
        active_playlist (str): Name of the currently active playlist.
    """

    DEFAULT_PLAYLIST_START = "00:00"
    DEFAULT_PLAYLIST_END = "24:00"

    def __init__(self, playlists=None, active_playlist=None):
        """Initialize PlaylistManager with a list of playlists."""
        if playlists is None:
            playlists = []
        self.playlists = playlists
        self.active_playlist = active_playlist

    def get_playlist_names(self):
        """Returns a list of all playlist names."""
        return [p.name for p in self.playlists]

    def add_default_playlist(self):
        """Add a default playlist to the manager, called when no playlists exist."""
        return self.playlists.append(
            Playlist(
                "Default",
                PlaylistManager.DEFAULT_PLAYLIST_START,
                PlaylistManager.DEFAULT_PLAYLIST_END,
                [],
            )
        )

    def find_plugin(self, plugin_id, instance):
        """Searches playlists to find a plugin with the given ID and instance."""
        for playlist in self.playlists:
            plugin = playlist.find_plugin(plugin_id, instance)
            if plugin:
                return plugin
        return None

    def determine_active_playlist(self, current_datetime):
        """Determine the active playlist based on the current time."""
        current_time = current_datetime.strftime(
            "%H:%M"
        )  # Get current time in "HH:MM" format

        # get active playlists that have plugins
        active_playlists = [p for p in self.playlists if p.is_active(current_time)]
        if not active_playlists:
            return None

        # Sort playlists by priority
        active_playlists.sort(key=lambda p: p.get_priority())
        playlist = active_playlists[0]

        return playlist

    def get_playlist(self, playlist_name):
        """Returns the playlist with the specified name."""
        return next((p for p in self.playlists if p.name == playlist_name), None)

    def add_plugin_to_playlist(self, playlist_name, plugin_data):
        """Adds a plugin to a playlist by the specified name. Returns true if successfully added,
        False if playlist doesn't exist"""
        playlist = self.get_playlist(playlist_name)
        if playlist:
            if playlist.add_plugin(plugin_data):
                return True
        else:
            logger.warning(f"Playlist '{playlist_name}' not found.")
        return False

    def add_playlist(self, name, start_time=None, end_time=None):
        """Creates and adds a new playlist with the given start and end times."""
        if not start_time:
            start_time = PlaylistManager.DEFAULT_PLAYLIST_START
        if not end_time:
            end_time = PlaylistManager.DEFAULT_PLAYLIST_END
        self.playlists.append(Playlist(name, start_time, end_time))
        return True

    def update_playlist(self, old_name, new_name, start_time, end_time):
        """Updates an existing playlist's name, start time, and end time."""
        playlist = self.get_playlist(old_name)
        if playlist:
            playlist.name = new_name
            playlist.start_time = start_time
            playlist.end_time = end_time
            return True
        logger.warning(f"Playlist '{old_name}' not found.")
        return False

    def delete_playlist(self, name):
        """Deletes the playlist with the specified name."""
        self.playlists = [p for p in self.playlists if p.name != name]

    def to_dict(self):
        return {
            "playlists": [p.to_dict() for p in self.playlists],
            "active_playlist": self.active_playlist,
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            playlists=[Playlist.from_dict(p) for p in data.get("playlists", [])],
            active_playlist=data.get("active_playlist"),
        )

    @staticmethod
    def should_refresh(latest_refresh, interval_seconds, current_time):
        """Determines whether a refresh should occur on the interval and latest refresh time."""
        if not latest_refresh:
            return True  # No previous refresh, so it's time to refresh

        return (current_time - latest_refresh) >= timedelta(seconds=interval_seconds)


class Playlist:
    """Represents a playlist with a time interval.

    Attributes:
        name (str): Name of the playlist.
        start_time (str): Playlist start time in 'HH:MM'.
        end_time (str): Playlist end time in 'HH:MM'.
        plugins (list): A list of PluginInstance objects within the playlist.
        current_plugin_index (int): Index of the currently active plugin in the playlist.
    """

    def __init__(
        self, name, start_time, end_time, plugins=None, current_plugin_index=None
    ):
        self.name = name
        self.start_time = start_time
        self.end_time = end_time
        self.plugins = [PluginInstance.from_dict(p) for p in (plugins or [])]
        self.current_plugin_index = current_plugin_index

    def is_active(self, current_time):
        """Check if the playlist is active at the given time."""
        return self.start_time <= current_time < self.end_time

    def add_plugin(self, plugin_data):
        """Add a new plugin instance to the playlist."""
        if self.find_plugin(plugin_data["plugin_id"], plugin_data["name"]):
            logger.warning(
                f"Plugin '{plugin_data['plugin_id']}' with instance '{plugin_data['name']}' already exists."
            )
            return False
        self.plugins.append(PluginInstance.from_dict(plugin_data))
        return True

    def update_plugin(self, plugin_id, instance_name, updated_data):
        """Updates an existing plugin instance in the playlist."""
        plugin = self.find_plugin(plugin_id, instance_name)
        if plugin:
            plugin.update(updated_data)
            return True
        logger.warning(f"Plugin '{plugin_id}' with name '{instance_name}' not found.")
        return False

    def delete_plugin(self, plugin_id, name):
        """Remove a specific plugin instance from the playlist."""
        initial_count = len(self.plugins)
        self.plugins = [
            p for p in self.plugins if not (p.plugin_id == plugin_id and p.name == name)
        ]

        if len(self.plugins) == initial_count:
            logger.warning(f"Plugin '{plugin_id}' with instance '{name}' not found.")
            return False
        return True

    def find_plugin(self, plugin_id, name):
        """Find a plugin instance by its plugin_id and name."""
        return next(
            (p for p in self.plugins if p.plugin_id == plugin_id and p.name == name),
            None,
        )

    def get_next_plugin(self):
        """Returns the next plugin instance in the playlist and update the current_plugin_index."""
        if not self.plugins:
            raise RuntimeError(f"Playlist '{self.name}' has no plugins configured.")

        if self.current_plugin_index is None:
            self.current_plugin_index = 0
        else:
            # Guard against corrupted index outside bounds
            if not (0 <= self.current_plugin_index < len(self.plugins)):
                self.current_plugin_index = 0
            else:
                self.current_plugin_index = (self.current_plugin_index + 1) % len(
                    self.plugins
                )

        return self.plugins[self.current_plugin_index]

    def peek_next_plugin(self):
        """Returns the next plugin instance without mutating the current index.

        If the index is unset or invalid, returns the first plugin as the next candidate.
        """
        if not self.plugins:
            return None

        if self.current_plugin_index is None:
            return self.plugins[0]

        if not (0 <= self.current_plugin_index < len(self.plugins)):
            return self.plugins[0]

        next_index = (self.current_plugin_index + 1) % len(self.plugins)
        return self.plugins[next_index]

    def get_next_eligible_plugin(self, current_time: datetime):
        """Advance to and return the next eligible plugin based on current_time.

        Tries up to N plugins (size of list) to find one that is_show_eligible.
        Mutates current_plugin_index similarly to get_next_plugin.
        Returns None if no eligible plugin is found.
        """
        if not self.plugins:
            return None

        original_index = self.current_plugin_index
        attempts = 0
        while attempts < len(self.plugins):
            # compute next index like get_next_plugin without committing first
            if self.current_plugin_index is None:
                next_index = 0
            else:
                if not (0 <= self.current_plugin_index < len(self.plugins)):
                    next_index = 0
                else:
                    next_index = (self.current_plugin_index + 1) % len(self.plugins)

            candidate = self.plugins[next_index]
            if candidate.is_show_eligible(current_time):
                self.current_plugin_index = next_index
                return candidate

            # advance and try again
            self.current_plugin_index = next_index
            attempts += 1

        # none eligible; restore index
        self.current_plugin_index = original_index
        return None

    def peek_next_eligible_plugin(self, current_time: datetime):
        """Return next eligible plugin without changing current_plugin_index."""
        saved = self.current_plugin_index
        try:
            return self.get_next_eligible_plugin(current_time)
        finally:
            self.current_plugin_index = saved

    def reorder_plugins(self, ordered_pairs):
        """Reorder plugins using a list of ordered (plugin_id, name) pairs.

        The ordered_pairs may be a list of tuples or dicts with keys 'plugin_id' and 'name'.
        Returns True on success, False if validation fails.
        """
        if not isinstance(ordered_pairs, list):
            return False

        def _key_for(p_inst):
            return (p_inst.plugin_id, p_inst.name)

        mapping = {(_key_for(p)): p for p in self.plugins}

        normalized_keys: list[tuple] = []
        for item in ordered_pairs:
            if isinstance(item, dict):
                pid = item.get("plugin_id")
                name = item.get("name") or item.get("instance_name")
                normalized_keys.append((pid, name))
            elif isinstance(item, (list, tuple)) and len(item) == 2:
                normalized_keys.append((item[0], item[1]))
            else:
                return False

        # Validate count and membership
        if len(normalized_keys) != len(self.plugins):
            return False
        try:
            new_order = [mapping[(pid, name)] for (pid, name) in normalized_keys]
        except KeyError:
            return False

        self.plugins = new_order
        # Reset index within bounds after reorder
        if self.current_plugin_index is not None:
            if not (0 <= self.current_plugin_index < len(self.plugins)):
                self.current_plugin_index = 0
        return True

    def get_priority(self):
        """Determine priority of a playlist, based on the time range"""
        return self.get_time_range_minutes()

    def get_time_range_minutes(self):
        """Calculate the time difference in minutes between start_time and end_time."""
        start = datetime.strptime(self.start_time, "%H:%M")
        # Handle '24:00' by converting it to '00:00' of the next day
        if self.end_time != "24:00":
            end = datetime.strptime(self.end_time, "%H:%M")
        else:
            end = datetime.strptime("00:00", "%H:%M")
            end += timedelta(days=1)

        return int((end - start).total_seconds() // 60)

    def to_dict(self):
        return {
            "name": self.name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "plugins": [p.to_dict() for p in self.plugins],
            "current_plugin_index": self.current_plugin_index,
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            name=data["name"],
            start_time=data["start_time"],
            end_time=data["end_time"],
            plugins=data["plugins"],
            current_plugin_index=data.get("current_plugin_index", None),
        )


class PluginInstance:
    """Represents an individual plugin instance within a playlist.

    Attributes:
        plugin_id (str): Plugin id for this instance.
        name (str): Name of the plugin instance.
        settings (dict): Settings associated with the plugin.
        refresh (dict): Refresh settings, such as interval and scheduled time.
        latest_refresh (str): ISO-formatted string representing the last refresh time.
    """

    def __init__(self, plugin_id, name, settings, refresh, latest_refresh_time=None, only_show_when_fresh=False, snooze_until=None):
        self.plugin_id = plugin_id
        self.name = name
        self.settings = settings
        self.refresh = refresh
        self.latest_refresh_time = latest_refresh_time
        self.only_show_when_fresh = only_show_when_fresh
        self.snooze_until = snooze_until

    def update(self, updated_data):
        """Update attributes of the class with the dictionary values."""
        for key, value in updated_data.items():
            setattr(self, key, value)

    def should_refresh(self, current_time: datetime) -> bool:
        """Checks whether the plugin should be refreshed based on its refresh settings and the current time."""
        latest_refresh_dt = self.get_latest_refresh_dt()
        if not latest_refresh_dt:
            return True

        # Check for interval-based refresh
        if "interval" in self.refresh:
            interval = self.refresh.get("interval")
            if interval and (current_time - latest_refresh_dt) >= timedelta(
                seconds=interval
            ):
                return True

        # Check for scheduled refresh (HH:MM format)
        if "scheduled" in self.refresh:
            scheduled_time_str = self.refresh.get("scheduled")
            latest_refresh_str = latest_refresh_dt.strftime("%H:%M")

            # If the latest refresh is before the scheduled time today
            if latest_refresh_str < scheduled_time_str:
                return True

        if "scheduled" in self.refresh:
            scheduled_time_str = self.refresh.get("scheduled")
            scheduled_time = datetime.strptime(scheduled_time_str, "%H:%M").time()

            latest_refresh_date = latest_refresh_dt.date()
            current_date = current_time.date()

            # Determine if a refresh is needed based on scheduled time and last refresh
            if (
                latest_refresh_date < current_date
                and current_time.time() >= scheduled_time
            ) or (
                latest_refresh_date == current_date
                and latest_refresh_dt.time() < scheduled_time <= current_time.time()
            ):
                return True

        return False

    def is_show_eligible(self, current_time: datetime) -> bool:
        """Determine if this instance should be considered for display now.

        - If snoozed until a future time, not eligible
        - If only_show_when_fresh, only eligible when should_refresh(current_time) is True
        """
        try:
            if self.snooze_until:
                try:
                    snooze_dt = datetime.fromisoformat(self.snooze_until)
                    if snooze_dt.tzinfo is None:
                        # Treat naive as UTC
                        from datetime import timezone

                        snooze_dt = snooze_dt.replace(tzinfo=timezone.utc)
                    if current_time < snooze_dt:
                        return False
                except Exception:
                    # Ignore malformed snooze value
                    pass

            # Only-fresh behavior removed: triggering display will generate or reuse as configured
            return True
        except Exception:
            return True

    def get_image_path(self):
        """Formats the image path for this plugin instance."""
        return f"{self.plugin_id}_{self.name.replace(' ', '_')}.png"

    def get_latest_refresh_dt(self):
        """Returns the latest refresh time as a datetime object, or None if not set."""
        latest_refresh = None
        if self.latest_refresh_time:
            latest_refresh = datetime.fromisoformat(self.latest_refresh_time)
        return latest_refresh

    def to_dict(self):
        return {
            "plugin_id": self.plugin_id,
            "name": self.name,
            "plugin_settings": self.settings,
            "refresh": self.refresh,
            "latest_refresh_time": self.latest_refresh_time,
            "only_show_when_fresh": self.only_show_when_fresh,
            "snooze_until": self.snooze_until,
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            plugin_id=data["plugin_id"],
            name=data["name"],
            settings=data["plugin_settings"],
            refresh=data["refresh"],
            latest_refresh_time=data.get("latest_refresh_time"),
            only_show_when_fresh=data.get("only_show_when_fresh", False),
            snooze_until=data.get("snooze_until"),
        )
