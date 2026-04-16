from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


def _sanitize_log_value(value: object) -> str:
    """Sanitize a value for safe inclusion in log messages."""
    text = str(value) if not isinstance(value, str) else value
    # Strip control characters that could enable log injection
    return text.translate(str.maketrans("", "", "\r\n\t\x00"))


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
        refresh_type: str | None,
        plugin_id: str | None,
        refresh_time: str | None,
        image_hash: int | None,
        playlist: str | None = None,
        plugin_instance: str | None = None,
        # Optional performance metrics
        request_ms: int | None = None,
        display_ms: int | None = None,
        generate_ms: int | None = None,
        preprocess_ms: int | None = None,
        used_cached: bool | None = None,
        # Optional benchmark correlation id
        benchmark_id: str | None = None,
        # Optional plugin-specific metadata
        plugin_meta: dict[str, Any] | None = None,
    ) -> None:
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
        # Optional benchmark correlation id so other components can attach stage events
        self.benchmark_id = benchmark_id
        # Optional plugin-specific metadata (e.g., WPOTD date/description)
        self.plugin_meta = plugin_meta

    def get_refresh_datetime(self) -> datetime | None:
        """Returns the refresh time as a datetime object or None if not set."""
        latest_refresh = None
        if self.refresh_time:
            latest_refresh = datetime.fromisoformat(self.refresh_time)
        return latest_refresh

    def to_dict(self) -> dict[str, Any]:
        refresh_dict: dict[str, Any] = {
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
        if getattr(self, "benchmark_id", None) is not None:
            refresh_dict["benchmark_id"] = self.benchmark_id
        # Include optional plugin metadata if available
        if getattr(self, "plugin_meta", None) is not None:
            refresh_dict["plugin_meta"] = self.plugin_meta
        return refresh_dict

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RefreshInfo:
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
            benchmark_id=data.get("benchmark_id"),
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

    def __init__(
        self,
        playlists: list[Playlist] | None = None,
        active_playlist: str | None = None,
    ) -> None:
        """Initialize PlaylistManager with a list of playlists."""
        if playlists is None:
            playlists = []
        self.playlists: list[Playlist] = playlists
        self.active_playlist = active_playlist

    def get_playlist_names(self) -> list[str]:
        """Returns a list of all playlist names."""
        return [p.name for p in self.playlists]

    def add_default_playlist(self) -> bool:
        """Add a default playlist to the manager, called when no playlists exist."""
        self.playlists.append(
            Playlist(
                "Default",
                PlaylistManager.DEFAULT_PLAYLIST_START,
                PlaylistManager.DEFAULT_PLAYLIST_END,
                [],
            )
        )
        return True

    def find_plugin(self, plugin_id: str, instance: str) -> PluginInstance | None:
        """Searches playlists to find a plugin with the given ID and instance."""
        for playlist in self.playlists:
            plugin = playlist.find_plugin(plugin_id, instance)
            if plugin:
                return plugin
        return None

    def determine_active_playlist(self, current_datetime: datetime) -> Playlist | None:
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
        return active_playlists[0]

    def get_playlist(self, playlist_name: str) -> Playlist | None:
        """Returns the playlist with the specified name."""
        return next((p for p in self.playlists if p.name == playlist_name), None)

    def add_plugin_to_playlist(
        self, playlist_name: str, plugin_data: dict[str, Any]
    ) -> bool:
        """Adds a plugin to a playlist by the specified name. Returns true if successfully added,
        False if playlist doesn't exist"""
        playlist = self.get_playlist(playlist_name)
        if playlist:
            if playlist.add_plugin(plugin_data):
                return True
        else:
            logger.warning(
                "Playlist '%s' not found.", _sanitize_log_value(playlist_name)
            )
        return False

    def add_playlist(
        self,
        name: str,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> bool:
        """Creates and adds a new playlist with the given start and end times."""
        if not start_time:
            start_time = PlaylistManager.DEFAULT_PLAYLIST_START
        if not end_time:
            end_time = PlaylistManager.DEFAULT_PLAYLIST_END
        self.playlists.append(Playlist(name, start_time, end_time))
        return True

    def update_playlist(
        self, old_name: str, new_name: str, start_time: str, end_time: str
    ) -> bool:
        """Updates an existing playlist's name, start time, and end time."""
        playlist = self.get_playlist(old_name)
        if playlist:
            playlist.name = new_name
            playlist.start_time = start_time
            playlist.end_time = end_time
            return True
        logger.warning("Playlist '%s' not found.", _sanitize_log_value(old_name))
        return False

    def delete_playlist(self, name: str) -> None:
        """Deletes the playlist with the specified name."""
        self.playlists = [p for p in self.playlists if p.name != name]

    def to_dict(self) -> dict[str, Any]:
        return {
            "playlists": [p.to_dict() for p in self.playlists],
            "active_playlist": self.active_playlist,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlaylistManager:
        return cls(
            playlists=[Playlist.from_dict(p) for p in data.get("playlists", [])],
            active_playlist=data.get("active_playlist"),
        )

    @staticmethod
    def should_refresh(
        latest_refresh: datetime | None,
        interval_seconds: float,
        current_time: datetime,
    ) -> bool:
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
        self,
        name: str,
        start_time: str,
        end_time: str,
        plugins: list[dict[str, Any]] | None = None,
        current_plugin_index: int | None = None,
        cycle_interval_seconds: int | None = None,
    ) -> None:
        self.name = name
        self.start_time = start_time
        self.end_time = end_time
        self.plugins: list[PluginInstance] = [
            PluginInstance.from_dict(p) for p in (plugins or [])
        ]
        self.current_plugin_index = current_plugin_index
        self.cycle_interval_seconds = cycle_interval_seconds

    @staticmethod
    def _to_minutes(time_str: str) -> int:
        """Convert an ``HH:MM`` string to minutes since midnight.

        ``24:00`` is treated as midnight of the following day (1440 minutes).
        Raises ``ValueError`` for out-of-range hours or minutes.
        """
        if time_str == "24:00":
            return 24 * 60
        hour, minute = map(int, time_str.split(":"))
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            raise ValueError("Invalid time")
        return hour * 60 + minute

    def is_active(self, current_time: str) -> bool:
        """Check if the playlist is active at the given time."""
        start = self._to_minutes(self.start_time)
        end = self._to_minutes(self.end_time)
        current = self._to_minutes(current_time)

        if start <= end:
            return start <= current < end
        return current >= start or current < end

    def add_plugin(self, plugin_data: dict[str, Any]) -> bool:
        """Add a new plugin instance to the playlist."""
        if self.find_plugin(plugin_data["plugin_id"], plugin_data["name"]):
            logger.warning(
                "Plugin '%s' with instance '%s' already exists.",
                _sanitize_log_value(plugin_data.get("plugin_id")),
                _sanitize_log_value(plugin_data.get("name")),
            )
            return False
        self.plugins.append(PluginInstance.from_dict(plugin_data))
        return True

    def update_plugin(
        self,
        plugin_id: str,
        instance_name: str,
        updated_data: dict[str, Any],
    ) -> bool:
        """Updates an existing plugin instance in the playlist."""
        plugin = self.find_plugin(plugin_id, instance_name)
        if plugin:
            plugin.update(updated_data)
            return True
        logger.warning(
            "Plugin '%s' with name '%s' not found.",
            _sanitize_log_value(plugin_id),
            _sanitize_log_value(instance_name),
        )
        return False

    def delete_plugin(self, plugin_id: str, name: str) -> bool:
        """Remove a specific plugin instance from the playlist."""
        initial_count = len(self.plugins)
        self.plugins = [
            p for p in self.plugins if not (p.plugin_id == plugin_id and p.name == name)
        ]

        if len(self.plugins) == initial_count:
            logger.warning(
                "Plugin '%s' with instance '%s' not found.",
                _sanitize_log_value(plugin_id),
                _sanitize_log_value(name),
            )
            return False
        return True

    def find_plugin(self, plugin_id: str, name: str) -> PluginInstance | None:
        """Find a plugin instance by its plugin_id and name."""
        return next(
            (p for p in self.plugins if p.plugin_id == plugin_id and p.name == name),
            None,
        )

    def get_next_plugin(self) -> PluginInstance:
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

    def peek_next_plugin(self) -> PluginInstance | None:
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

    def get_next_eligible_plugin(self, current_time: datetime) -> PluginInstance | None:
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

    def peek_next_eligible_plugin(
        self, current_time: datetime
    ) -> PluginInstance | None:
        """Return next eligible plugin without changing current_plugin_index."""
        saved = self.current_plugin_index
        try:
            return self.get_next_eligible_plugin(current_time)
        finally:
            self.current_plugin_index = saved

    def reorder_plugins(self, ordered_pairs: object) -> bool:
        """Reorder plugins using a list of ordered (plugin_id, name) pairs.

        The ordered_pairs may be a list of tuples or dicts with keys 'plugin_id' and 'name'.
        Returns True on success, False if validation fails.
        """
        if not isinstance(ordered_pairs, list):
            return False

        def _key_for(p_inst: PluginInstance) -> tuple[str, str]:
            return (p_inst.plugin_id, p_inst.name)

        mapping = {(_key_for(p)): p for p in self.plugins}

        normalized_keys: list[tuple[Any, Any]] = []
        for item in ordered_pairs:
            if isinstance(item, dict):
                pid = item.get("plugin_id")
                name = item.get("name") or item.get("instance_name")
                normalized_keys.append((pid, name))
            elif isinstance(item, list | tuple) and len(item) == 2:
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
        if self.current_plugin_index is not None and not (
            0 <= self.current_plugin_index < len(self.plugins)
        ):
            self.current_plugin_index = 0
        return True

    def get_priority(self) -> int:
        """Determine priority of a playlist, based on the time range"""
        return self.get_time_range_minutes()

    def get_time_range_minutes(self) -> int:
        """Calculate the duration in minutes between start_time and end_time.

        When ``start_time`` is later than ``end_time`` the range is assumed to
        wrap past midnight.
        """
        start = self._to_minutes(self.start_time)
        end = self._to_minutes(self.end_time)
        if end >= start:
            return end - start
        return (24 * 60 - start) + end

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "plugins": [p.to_dict() for p in self.plugins],
            "current_plugin_index": self.current_plugin_index,
        }
        if self.cycle_interval_seconds is not None:
            data["cycle_interval_seconds"] = self.cycle_interval_seconds
            data["cycle_minutes"] = int(self.cycle_interval_seconds) // 60
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Playlist:
        cycle_interval_seconds = data.get("cycle_interval_seconds")
        if cycle_interval_seconds is None:
            # Legacy configs used cycle_minutes; migrate to seconds on load.
            legacy_minutes = data.get("cycle_minutes")
            minutes: int | None = None
            if isinstance(legacy_minutes, int):
                minutes = legacy_minutes
            elif isinstance(legacy_minutes, str):
                try:
                    minutes = int(legacy_minutes.strip())
                except ValueError:
                    minutes = None
            if minutes is not None and minutes > 0:
                cycle_interval_seconds = minutes * 60

        plugins = data.get("plugins", [])
        if not isinstance(plugins, list):
            plugins = []

        return cls(
            name=data.get("name", "Default"),
            start_time=data.get("start_time", PlaylistManager.DEFAULT_PLAYLIST_START),
            end_time=data.get("end_time", PlaylistManager.DEFAULT_PLAYLIST_END),
            plugins=plugins,
            current_plugin_index=data.get("current_plugin_index"),
            cycle_interval_seconds=cycle_interval_seconds,
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

    # Only these attributes may be modified via update().  plugin_id is
    # intentionally excluded — it is an immutable identity field and must not
    # be overwritten by user-supplied data.
    _UPDATABLE: frozenset[str] = frozenset(
        {
            "name",
            "settings",
            "refresh",
            "latest_refresh_time",
            "only_show_when_fresh",
            "snooze_until",
        }
    )

    def __init__(
        self,
        plugin_id: str,
        name: str,
        settings: dict[str, Any],
        refresh: dict[str, Any],
        latest_refresh_time: str | None = None,
        only_show_when_fresh: bool = False,
        snooze_until: str | None = None,
        consecutive_failure_count: int = 0,
        paused: bool = False,
        disabled_reason: str | None = None,
    ) -> None:
        self.plugin_id = plugin_id
        self.name = name
        self.settings = settings
        self.refresh = refresh
        self.latest_refresh_time = latest_refresh_time
        self.only_show_when_fresh = only_show_when_fresh
        self.snooze_until = snooze_until
        self.consecutive_failure_count = consecutive_failure_count
        self.paused = paused
        self.disabled_reason = disabled_reason

    def update(self, updated_data: dict[str, Any]) -> None:
        """Update attributes of the class with the dictionary values.

        Only keys present in ``_UPDATABLE`` are applied; unknown keys are
        silently ignored to avoid breaking callers that pass extra data and to
        prevent arbitrary attribute injection.
        """
        for key, value in updated_data.items():
            if key in self._UPDATABLE:
                setattr(self, key, value)
            else:
                logger.debug(
                    "PluginInstance.update: ignoring non-updatable field %r",
                    key,
                )

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
            # Key presence was just checked above; indexing preserves prior
            # behavior while giving mypy an Any (vs Any | None from .get()).
            scheduled_time_str = self.refresh["scheduled"]
            try:
                # Parsing HH:MM into a time-of-day; no date/tz context is needed.
                scheduled_time = datetime.strptime(  # noqa: DTZ007
                    scheduled_time_str, "%H:%M"
                ).time()
            except (ValueError, TypeError):
                logger.warning(
                    "Malformed scheduled time '%s' for plugin '%s'; skipping scheduled check",
                    _sanitize_log_value(scheduled_time_str),
                    _sanitize_log_value(self.name),
                )
                return False

            # Build scheduled_dt using timedelta from midnight to avoid DST
            # pitfalls. current_time.replace(hour=h, minute=m) can raise
            # ValueError for non-existent spring-forward times and silently
            # picks the wrong fold for ambiguous fall-back times.
            midnight = current_time.replace(hour=0, minute=0, second=0, microsecond=0)
            scheduled_dt = midnight + timedelta(
                hours=scheduled_time.hour, minutes=scheduled_time.minute
            )

            # Align timezone awareness for comparison
            if scheduled_dt.tzinfo and latest_refresh_dt.tzinfo is None:
                latest_refresh_dt = latest_refresh_dt.replace(
                    tzinfo=scheduled_dt.tzinfo
                )
            elif latest_refresh_dt.tzinfo and scheduled_dt.tzinfo is None:
                scheduled_dt = scheduled_dt.replace(tzinfo=latest_refresh_dt.tzinfo)

            # Refresh if we haven't refreshed since today's scheduled time
            if latest_refresh_dt < scheduled_dt <= current_time:
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

                        snooze_dt = snooze_dt.replace(tzinfo=UTC)
                    if current_time < snooze_dt:
                        return False
                except (ValueError, TypeError):
                    logger.warning(
                        "Malformed snooze_until value '%s' for plugin '%s'; treating as eligible",
                        _sanitize_log_value(self.snooze_until),
                        _sanitize_log_value(self.name),
                    )

            return not (
                self.only_show_when_fresh and not self.should_refresh(current_time)
            )
        except Exception:
            logger.warning(
                "Unexpected error in is_show_eligible for plugin '%s'; treating as eligible",
                _sanitize_log_value(self.name),
                exc_info=True,
            )
            return True

    def get_image_path(self) -> str:
        """Formats the image path for this plugin instance."""
        return f"{self.plugin_id}_{self.name.replace(' ', '_')}.png"

    def get_latest_refresh_dt(self) -> datetime | None:
        """Returns the latest refresh time as a datetime object, or None if not set."""
        latest_refresh = None
        if self.latest_refresh_time:
            latest_refresh = datetime.fromisoformat(self.latest_refresh_time)
        return latest_refresh

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "plugin_id": self.plugin_id,
            "name": self.name,
            "plugin_settings": self.settings,
            "refresh": self.refresh,
            "latest_refresh_time": self.latest_refresh_time,
            "only_show_when_fresh": self.only_show_when_fresh,
            "snooze_until": self.snooze_until,
            "consecutive_failure_count": self.consecutive_failure_count,
            "paused": self.paused,
        }
        if self.disabled_reason is not None:
            d["disabled_reason"] = self.disabled_reason
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PluginInstance:
        plugin_settings = data.get("plugin_settings")
        if plugin_settings is None:
            # Legacy configs used "settings"; preserve user data on migration.
            plugin_settings = data.get("settings", {})
        if not isinstance(plugin_settings, dict):
            plugin_settings = {}

        refresh = data.get("refresh")
        if not isinstance(refresh, dict):
            refresh = {}
        if "scheduled" not in refresh and "schedule" in refresh:
            # Legacy field alias.
            refresh = dict(refresh)
            refresh["scheduled"] = refresh.get("schedule")

        raw_plugin_id = data.get("plugin_id", data.get("id"))
        if not isinstance(raw_plugin_id, str) or not raw_plugin_id.strip():
            logger.warning(
                "PluginInstance.from_dict: missing plugin_id/id; defaulting to 'unknown'. data_keys=%s",
                sorted(data.keys()),
            )
            raw_plugin_id = "unknown"

        return cls(
            plugin_id=raw_plugin_id,
            name=data.get(
                "name",
                data.get(
                    "instance_name", data.get("plugin_id", data.get("id", "unknown"))
                ),
            ),
            settings=plugin_settings,
            refresh=refresh,
            latest_refresh_time=data.get(
                "latest_refresh_time", data.get("latest_refresh")
            ),
            only_show_when_fresh=data.get("only_show_when_fresh", False),
            snooze_until=data.get("snooze_until"),
            consecutive_failure_count=data.get("consecutive_failure_count", 0),
            paused=data.get("paused", False),
            disabled_reason=data.get("disabled_reason"),
        )
