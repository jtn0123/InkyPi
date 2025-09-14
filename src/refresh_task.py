import logging
import os
import threading
from datetime import datetime
from time import perf_counter

from model import PlaylistManager, RefreshInfo
from plugins.plugin_registry import get_plugin_instance
from utils.image_utils import compute_image_hash, load_image_from_path
from utils.progress import ProgressTracker, track_progress
from utils.time_utils import now_device_tz
from uuid import uuid4

try:
    # Optional import; code must continue if unavailable
    from benchmarks.benchmark_storage import save_refresh_event, save_stage_event
except Exception:  # pragma: no cover
    def save_refresh_event(*args, **kwargs):  # type: ignore
        return None

    def save_stage_event(*args, **kwargs):  # type: ignore
        return None

logger = logging.getLogger(__name__)


class RefreshTask:
    """Handles the logic for refreshing the display using a backgroud thread."""

    def __init__(self, device_config, display_manager):
        self.device_config = device_config
        self.display_manager = display_manager

        self.thread = None
        self.lock = threading.Lock()
        self.condition = threading.Condition(self.lock)
        self.running = False
        # None until a manual refresh is requested; then set to a RefreshAction
        self.manual_update_request = None

        self.refresh_event = threading.Event()
        self.refresh_event.set()
        self.refresh_result = {}

    def start(self):
        """Starts the background thread for refreshing the display."""
        if not self.thread or not self.thread.is_alive():
            logger.info("Starting refresh task")
            self.thread = threading.Thread(
                target=self._run, daemon=True, name="RefreshTask"
            )
            self.running = True
            self.thread.start()

    def stop(self):
        """Stops the refresh task by notifying the background thread to exit."""
        with self.condition:
            self.running = False
            self.condition.notify_all()  # Wake the thread to let it exit
        if self.thread:
            logger.info("Stopping refresh task")
            self.thread.join(timeout=5)
            if self.thread.is_alive():
                logger.warning("Refresh task thread did not stop within timeout")

    def _run(self):
        """Background thread loop coordinating refresh operations.

        The method waits for either the configured interval or a manual trigger,
        selects the appropriate :class:`RefreshAction`, performs the refresh,
        and updates refresh metadata. Threading primitives are handled in helper
        methods to keep the flow readable.
        """
        while True:
            try:
                result = self._wait_for_trigger()
                if result is None:
                    break

                playlist_manager, latest_refresh, current_dt, manual_action = result
                refresh_action = self._select_refresh_action(
                    playlist_manager, latest_refresh, current_dt, manual_action
                )

                if refresh_action:
                    self.refresh_result = {}
                    self.refresh_event.clear()

                    refresh_info, used_cached, metrics = self._perform_refresh(
                        refresh_action, latest_refresh, current_dt
                    )
                    self.refresh_result["metrics"] = metrics
                    if refresh_info is not None:
                        self._update_refresh_info(refresh_info, metrics, used_cached)

            except Exception as e:
                logger.exception("Exception during refresh")
                self.refresh_result["exception"] = e  # Capture exception
            finally:
                self.refresh_event.set()

    def _wait_for_trigger(self):
        """Wait for the next refresh trigger while holding the condition lock.

        The method blocks for ``plugin_cycle_interval_seconds`` or until notified
        of a manual update. It returns the contextual objects required for the
        refresh cycle or ``None`` if the task was stopped.

        Threading:
            Acquires ``self.condition`` and releases it before returning.
        """
        with self.condition:
            sleep_time = self.device_config.get_config(
                "plugin_cycle_interval_seconds", default=60 * 60
            )
            self.condition.wait(timeout=sleep_time)
            if not self.running:
                return None

            playlist_manager = self.device_config.get_playlist_manager()
            latest_refresh = self.device_config.get_refresh_info()
            current_dt = self._get_current_datetime()
            manual_action = self.manual_update_request
            if manual_action is not None:
                self.manual_update_request = None
            return playlist_manager, latest_refresh, current_dt, manual_action

    def _select_refresh_action(
        self, playlist_manager, latest_refresh, current_dt, manual_action
    ):
        """Determine which refresh action to perform.

        If ``manual_action`` is provided it is returned immediately. Otherwise,
        the next eligible plugin is selected based on playlists.

        Threading:
            No locks are held during execution.
        """
        refresh_action = None
        if manual_action is not None:
            logger.info("Manual update requested")
            refresh_action = manual_action
        else:
            if self.device_config.get_config("log_system_stats"):
                self.log_system_stats()
            logger.info(
                f"Running interval refresh check. | current_time: {current_dt.strftime('%Y-%m-%d %H:%M:%S')}"
            )
            playlist, plugin_instance = self._determine_next_plugin(
                playlist_manager, latest_refresh, current_dt
            )
            if plugin_instance:
                refresh_action = PlaylistRefresh(playlist, plugin_instance)
        return refresh_action

    def _perform_refresh(self, refresh_action, latest_refresh, current_dt):
        """Execute the refresh action and update the display if needed.

        Returns a tuple ``(refresh_info, used_cached, metrics)`` where
        ``refresh_info`` is a dictionary with metadata, ``used_cached`` indicates
        whether the image was unchanged, and ``metrics`` contains timing data.

        Threading:
            Must be called without holding ``self.condition``.
        """
        plugin_config = self.device_config.get_plugin(refresh_action.get_plugin_id())
        if plugin_config is None:
            logger.error(
                f"Plugin config not found for '{refresh_action.get_plugin_id()}'."
            )
            return None, False, {}

        plugin = get_plugin_instance(plugin_config)
        _t_req_start = perf_counter()
        # Correlate this refresh with a benchmark id so parallel stage events can attach
        benchmark_id = str(uuid4())
        _t_gen_start = perf_counter()
        tracker: ProgressTracker
        with track_progress() as tracker:
            stage_t0 = perf_counter()
            image = refresh_action.execute(plugin, self.device_config, current_dt)
            try:
                save_stage_event(
                    self.device_config,
                    benchmark_id,
                    "generate_image",
                    int((perf_counter() - stage_t0) * 1000),
                )
            except Exception:
                pass
        generate_ms = int((perf_counter() - _t_gen_start) * 1000)
        if image is None:
            raise RuntimeError("Plugin returned None image; cannot refresh display.")
        image_hash = compute_image_hash(image)

        refresh_info = refresh_action.get_refresh_info()
        try:
            plugin_meta = None
            if hasattr(plugin, "get_latest_metadata"):
                plugin_meta = plugin.get_latest_metadata()
            if plugin_meta:
                refresh_info.update({"plugin_meta": plugin_meta})
        except Exception as exc:
            logger.warning(
                "Error getting latest metadata for plugin %s: %s",
                refresh_action.get_plugin_id(),
                exc,
            )

        refresh_info.update(
            {"refresh_time": current_dt.isoformat(), "image_hash": image_hash}
        )
        used_cached = image_hash == latest_refresh.image_hash
        if not used_cached:
            logger.info(f"Updating display. | refresh_info: {refresh_info}")
            history_meta = {
                "refresh_type": refresh_action.get_refresh_info().get("refresh_type"),
                "plugin_id": refresh_action.get_refresh_info().get("plugin_id"),
                "playlist": refresh_action.get_refresh_info().get("playlist"),
                "plugin_instance": refresh_action.get_refresh_info().get(
                    "plugin_instance"
                ),
            }
            try:
                # Mark preprocess/display as stages around display_manager call
                stage_t1 = perf_counter()
                self.display_manager.display_image(
                    image,
                    image_settings=plugin.config.get("image_settings", []),
                    history_meta=history_meta,
                )
            except TypeError:
                stage_t1 = perf_counter()
                self.display_manager.display_image(
                    image,
                    image_settings=plugin.config.get("image_settings", []),
                )
            finally:
                try:
                    save_stage_event(
                        self.device_config,
                        benchmark_id,
                        "display_pipeline",
                        int((perf_counter() - stage_t1) * 1000),
                    )
                except Exception:
                    pass
        else:
            logger.info(
                f"Image already displayed, skipping refresh. | refresh_info: {refresh_info}"
            )

        request_ms = int((perf_counter() - _t_req_start) * 1000)
        dm_info = getattr(self.device_config, "refresh_info", None)
        display_ms = getattr(dm_info, "display_ms", None) if dm_info else None
        preprocess_ms = getattr(dm_info, "preprocess_ms", None) if dm_info else None
        metrics = {
            "request_ms": request_ms,
            "display_ms": display_ms,
            "generate_ms": generate_ms,
            "preprocess_ms": preprocess_ms,
            "steps": tracker.get_steps(),
        }
        # Persist a refresh_event row best-effort
        try:
            # capture lightweight system snapshot
            cpu_percent = memory_percent = None
            try:
                import psutil  # type: ignore

                cpu_percent = psutil.cpu_percent(interval=None)
                memory_percent = psutil.virtual_memory().percent
            except Exception:
                pass
            save_refresh_event(
                self.device_config,
                {
                    "refresh_id": benchmark_id,
                    "ts": None,
                    "plugin_id": refresh_info.get("plugin_id"),
                    "instance": refresh_info.get("plugin_instance"),
                    "playlist": refresh_info.get("playlist"),
                    "used_cached": used_cached,
                    "request_ms": request_ms,
                    "generate_ms": generate_ms,
                    "preprocess_ms": preprocess_ms,
                    "display_ms": display_ms,
                    "cpu_percent": cpu_percent,
                    "memory_percent": memory_percent,
                    "notes": None,
                },
            )
        except Exception:
            pass
        return refresh_info | {"benchmark_id": benchmark_id}, used_cached, metrics

    def _update_refresh_info(self, refresh_info, metrics, used_cached):
        """Persist the latest refresh information to the device config.

        Threading:
            Should be invoked without holding ``self.condition``.
        """
        self.device_config.refresh_info = RefreshInfo(
            **refresh_info,
            request_ms=metrics.get("request_ms"),
            display_ms=metrics.get("display_ms"),
            generate_ms=metrics.get("generate_ms"),
            preprocess_ms=metrics.get("preprocess_ms"),
            used_cached=used_cached,
        )
        self.device_config.write_config()

    def manual_update(self, refresh_action):
        """Manually triggers an update for the specified plugin id and plugin settings by notifying the background process."""
        if self.running:
            with self.condition:
                self.manual_update_request = refresh_action
                self.refresh_result = {}
                self.refresh_event.clear()

                self.condition.notify_all()  # Wake the thread to process manual update

            self.refresh_event.wait()
            metrics = self.refresh_result.get("metrics")
            exc = self.refresh_result.get("exception")
            if exc is not None:
                if isinstance(exc, BaseException):
                    raise exc
                raise RuntimeError(str(exc))
            return metrics
        else:
            logger.warning(
                "Background refresh task is not running, unable to do a manual update"
            )
            # If task was never started (no thread), surface any captured exception
            # to callers. If the thread exists (even if stopped), treat as a no-op
            # because the background cycle already handled signaling.
            if self.thread is None:
                exc = self.refresh_result.get("exception")
                if exc is not None:
                    if isinstance(exc, BaseException):
                        raise exc
                    raise RuntimeError(str(exc))
            return self.refresh_result.get("metrics")

    def signal_config_change(self):
        """Notify the background thread that config has changed (e.g., interval updated)."""
        if self.running:
            with self.condition:
                self.condition.notify_all()

    def _get_current_datetime(self):
        """Retrieves the current datetime based on the device's configured timezone."""
        return now_device_tz(self.device_config)

    def _determine_next_plugin(self, playlist_manager, latest_refresh_info, current_dt):
        """Determines the next plugin to refresh based on the active playlist, plugin cycle interval, and current time."""
        playlist = playlist_manager.determine_active_playlist(current_dt)
        if not playlist:
            playlist_manager.active_playlist = None
            logger.info("No active playlist determined.")
            return None, None

        playlist_manager.active_playlist = playlist.name
        if not playlist.plugins:
            logger.info(f"Active playlist '{playlist.name}' has no plugins.")
            return None, None

        latest_refresh_dt = latest_refresh_info.get_refresh_datetime()
        # Allow per-playlist override; fallback to device-level interval
        plugin_cycle_interval = getattr(
            playlist, "cycle_interval_seconds", None
        ) or self.device_config.get_config(
            "plugin_cycle_interval_seconds", default=3600
        )
        should_refresh = PlaylistManager.should_refresh(
            latest_refresh_dt, plugin_cycle_interval, current_dt
        )

        if not should_refresh:
            latest_refresh_str = (
                latest_refresh_dt.strftime("%Y-%m-%d %H:%M:%S")
                if latest_refresh_dt
                else "None"
            )
            logger.info(
                f"Not time to update display. | latest_update: {latest_refresh_str} | plugin_cycle_interval: {plugin_cycle_interval}"
            )
            return None, None

        # Use eligibility-aware selection
        plugin = playlist.get_next_eligible_plugin(current_dt)
        if plugin:
            logger.info(
                f"Determined next plugin. | active_playlist: {playlist.name} | plugin_instance: {plugin.name}"
            )
            return playlist, plugin

        logger.info(
            f"No eligible plugin to display in active playlist '{playlist.name}'."
        )
        return None, None

    def log_system_stats(self):
        try:
            import psutil
        except Exception:
            logger.info("System Stats: psutil not available")
            return

        metrics = {
            # interval=None ensures a non-blocking snapshot of CPU usage
            "cpu_percent": psutil.cpu_percent(interval=None),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_percent": psutil.disk_usage("/").percent,
            "swap_percent": psutil.swap_memory().percent,
            "net_io": {
                "bytes_sent": psutil.net_io_counters().bytes_sent,
                "bytes_recv": psutil.net_io_counters().bytes_recv,
            },
        }

        try:
            metrics["load_avg_1_5_15"] = os.getloadavg()
        except (OSError, AttributeError):
            metrics["load_avg_1_5_15"] = None

        logger.info(f"System Stats: {metrics}")


class RefreshAction:
    """Base class for a refresh action.

    Subclasses must implement :meth:`execute` to perform the refresh operation
    and return the resulting image.
    """

    def execute(self, plugin, device_config, current_dt):
        """Execute the refresh operation and return the updated image."""
        raise NotImplementedError("Subclasses must implement the execute method.")

    def get_refresh_info(self):
        """Return refresh metadata as a dictionary."""
        raise NotImplementedError(
            "Subclasses must implement the get_refresh_info method."
        )

    def get_plugin_id(self):
        """Return the plugin ID associated with this refresh."""
        raise NotImplementedError("Subclasses must implement the get_plugin_id method.")


class ManualRefresh(RefreshAction):
    """Performs a manual refresh based on a plugin's ID and its associated settings.

    Attributes:
        plugin_id (str): The ID of the plugin to refresh.
        plugin_settings (dict): The settings for the manual refresh.
    """

    def __init__(self, plugin_id: str, plugin_settings: dict):
        self.plugin_id = plugin_id
        self.plugin_settings = plugin_settings

    def execute(self, plugin, device_config, current_dt: datetime):
        """Performs a manual refresh using the stored plugin ID and settings."""
        return plugin.generate_image(self.plugin_settings, device_config)

    def get_refresh_info(self):
        """Return refresh metadata as a dictionary."""
        return {"refresh_type": "Manual Update", "plugin_id": self.plugin_id}

    def get_plugin_id(self):
        """Return the plugin ID associated with this refresh."""
        return self.plugin_id


class PlaylistRefresh(RefreshAction):
    """Performs a refresh using a plugin instance within a playlist context.

    Attributes:
        playlist: The playlist object associated with the refresh.
        plugin_instance: The plugin instance to refresh.
    """

    def __init__(self, playlist, plugin_instance, force=False):
        self.playlist = playlist
        self.plugin_instance = plugin_instance
        self.force = force

    def get_refresh_info(self):
        """Return refresh metadata as a dictionary."""
        return {
            "refresh_type": "Playlist",
            "playlist": self.playlist.name,
            "plugin_id": self.plugin_instance.plugin_id,
            "plugin_instance": self.plugin_instance.name,
        }

    def get_plugin_id(self):
        """Return the plugin ID associated with this refresh."""
        return self.plugin_instance.plugin_id

    def execute(self, plugin, device_config, current_dt: datetime):
        """Performs a refresh for the specified plugin instance within its playlist context."""
        # Determine the file path for the plugin's image
        plugin_image_path = os.path.join(
            device_config.plugin_image_dir, self.plugin_instance.get_image_path()
        )

        # Check if a refresh is needed based on the plugin instance's criteria
        if self.plugin_instance.should_refresh(current_dt) or self.force:
            logger.info(
                f"Refreshing plugin instance. | plugin_instance: '{self.plugin_instance.name}'"
            )
            # Generate a new image
            image = plugin.generate_image(self.plugin_instance.settings, device_config)
            image.save(plugin_image_path)
            self.plugin_instance.latest_refresh_time = current_dt.isoformat()
        else:
            logger.info(
                f"Not time to refresh plugin instance, using latest image. | plugin_instance: {self.plugin_instance.name}."
            )
            # Load the existing image from disk using standardized helper
            image = load_image_from_path(plugin_image_path)
            if image is None:
                raise RuntimeError("Failed to load existing plugin image from disk")

        return image
