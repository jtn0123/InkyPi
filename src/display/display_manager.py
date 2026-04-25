import fnmatch
import json
import logging
import os
import threading
from collections.abc import Callable, Mapping
from time import perf_counter
from typing import Any, Protocol, cast

from PIL import Image

from display.abstract_display import AbstractDisplay, DeviceConfigLike
from display.mock_display import MockDisplay
from utils.image_utils import apply_image_enhancement, change_orientation, resize_image
from utils.time_utils import now_device_tz

logger = logging.getLogger(__name__)


class _DisplayLike(Protocol):
    def display_image(
        self, image: Image.Image, image_settings: list[object] | None = None
    ) -> None: ...


# Try to import hardware displays, but don't fail if they're not available
InkyDisplay: type[AbstractDisplay] | None = None
try:
    from display.inky_display import InkyDisplay as _InkyDisplay

    InkyDisplay = _InkyDisplay
except ImportError:
    logger.info("Inky display not available, hardware support disabled")

WaveshareDisplay: type[AbstractDisplay] | None = None
try:
    from display.waveshare_display import WaveshareDisplay as _WaveshareDisplay

    WaveshareDisplay = _WaveshareDisplay
except ImportError:
    logger.info("Waveshare display not available, hardware support disabled")


class DisplayManager:
    """Manages the display and rendering of images."""

    def __init__(self, device_config: DeviceConfigLike) -> None:
        """
        Initializes the display manager and selects the correct display type
        based on the configuration.

        Args:
            device_config (object): Configuration object containing display settings.

        Raises:
            ValueError: If an unsupported display type is specified.
        """

        self._last_image_hash: str | None = None
        self._hash_lock = threading.Lock()
        self.device_config = device_config
        self.display: _DisplayLike

        display_type = str(device_config.get_config("display_type", default="inky"))

        if display_type == "mock":
            self.display = MockDisplay(device_config)
        elif display_type == "inky":
            if InkyDisplay is None:
                raise RuntimeError(
                    "Display type 'inky' requested but the Inky hardware driver is unavailable."
                )
            self.display = InkyDisplay(device_config)
        elif fnmatch.fnmatch(display_type, "epd*in*"):
            if WaveshareDisplay is None:
                raise RuntimeError(
                    f"Display type '{display_type}' requested but the Waveshare driver is unavailable."
                )
            # derived from waveshare epd - we assume here that will be consistent
            # otherwise we will have to enshring the manufacturer in the
            # display_type and then have a display_model parameter.  Will leave
            # that for future use if the need arises.
            #
            # see https://github.com/waveshareteam/e-Paper
            self.display = WaveshareDisplay(device_config)
        else:
            raise ValueError(f"Unsupported display type: {display_type}")

    # Maximum number of history snapshots to keep. Oldest entries beyond this
    # limit are pruned after each new save. Override via INKYPI_HISTORY_MAX_ENTRIES.
    HISTORY_MAX_ENTRIES = int(os.getenv("INKYPI_HISTORY_MAX_ENTRIES", "500") or "500")

    # Approximate count of history entries to avoid scanning the directory on
    # every save.  Reset to None to force a recount on the next prune cycle.
    _history_count_estimate: int | None = None
    # Force a full recount every N increments to correct estimate drift
    _RECOUNT_INTERVAL = 50
    _history_increment_count = 0
    _history_lock = threading.RLock()

    def _prune_history(self, history_dir: str) -> None:
        """Remove oldest history entries when the total exceeds HISTORY_MAX_ENTRIES.

        Uses an in-memory count estimate to skip the directory scan when the
        count is clearly below the limit.  The estimate is refreshed whenever
        an actual scan is performed or every _RECOUNT_INTERVAL increments.
        """
        with self._history_lock:
            if (
                self._history_count_estimate is not None
                and self._history_count_estimate < self.HISTORY_MAX_ENTRIES
            ):
                self._history_count_estimate += 1
                self._history_increment_count += 1
                # Force periodic recount to correct drift from external deletions
                if self._history_increment_count < self._RECOUNT_INTERVAL:
                    return
                self._history_increment_count = 0
            try:
                png_files: list[str] = sorted(
                    (f for f in os.listdir(history_dir) if f.endswith(".png")),
                    key=lambda name: (
                        os.path.getmtime(os.path.join(history_dir, name)),
                        name,
                    ),
                )
                self._history_count_estimate = len(png_files)
                excess = len(png_files) - self.HISTORY_MAX_ENTRIES
                if excess <= 0:
                    return
                for name in png_files[:excess]:
                    base = name.rsplit(".", 1)[0]
                    for ext in (".png", ".json"):
                        path = os.path.join(history_dir, base + ext)
                        try:
                            os.remove(path)
                        except FileNotFoundError:
                            pass
                self._history_count_estimate = len(png_files) - excess
                logger.info(
                    "Pruned %d old history entries (max %d)",
                    excess,
                    self.HISTORY_MAX_ENTRIES,
                )
            except OSError:
                logger.debug("Could not prune history directory", exc_info=True)

    def _save_history_entry(
        self,
        processed_image: Image.Image,
        history_meta: Mapping[str, object] | None = None,
    ) -> None:
        """Persist a processed image snapshot and optional JSON sidecar metadata."""
        history_dir_raw = getattr(self.device_config, "history_image_dir", None)
        if not isinstance(history_dir_raw, str) or not history_dir_raw:
            return

        history_dir = history_dir_raw
        try:
            with self._history_lock:
                os.makedirs(history_dir, exist_ok=True)
                timestamp = now_device_tz(cast(Any, self.device_config))
                base_name = f"display_{timestamp.strftime('%Y%m%d_%H%M%S')}"

                png_path: str | None = None
                for attempt in range(1000):
                    candidate = (
                        base_name if attempt == 0 else f"{base_name}_{attempt:03d}"
                    )
                    candidate_path = os.path.join(history_dir, f"{candidate}.png")
                    if os.path.exists(candidate_path):
                        continue
                    processed_image.save(candidate_path, optimize=True)
                    base_name = candidate
                    png_path = candidate_path
                    break

                if png_path is None:
                    raise OSError("Unable to allocate a unique history snapshot path")
        except (OSError, ValueError, RuntimeError):
            logger.exception("Failed to save history snapshot image")
            return
        try:
            meta_payload = dict(history_meta or {})
            meta_payload.setdefault("refresh_time", timestamp.isoformat())
            with open(
                os.path.join(history_dir, f"{base_name}.json"),
                "w",
                encoding="utf-8",
            ) as fh:
                json.dump(meta_payload, fh)
        except (OSError, TypeError, ValueError):
            logger.exception("Failed to persist history metadata for %s", base_name)
        self._prune_history(history_dir)

    def display_image(
        self,
        image: Image.Image,
        image_settings: list[object] | None = None,
        history_meta: Mapping[str, object] | None = None,
        on_image_saved: Callable[[dict[str, int]], object] | None = None,
    ) -> dict[str, int | str]:
        """
        Delegates image rendering to the appropriate display instance.

        Args:
            image (PIL.Image): The image to be displayed.
            image_settings (list, optional): List of settings to modify image rendering.
            history_meta (dict, optional): Metadata persisted alongside the
                history snapshot.
            on_image_saved (callable, optional): Invoked once the processed
                image has been written to disk but before the (slow) hardware
                push.  Used by the manual-update path (JTN-786) to release the
                API caller without waiting for the SPI write to finish.
                Receives a metrics dict ``{"preprocess_ms": int}``.  Exceptions
                raised by the callback are logged but never propagated.

        Raises:
            ValueError: If no valid display instance is found.
        """
        if image_settings is None:
            image_settings = []

        if not hasattr(self, "display"):
            raise ValueError("No valid display instance initialized.")

        from utils.image_utils import compute_image_hash

        image_hash = cast(Any, compute_image_hash)(image)
        with self._hash_lock:
            if image_hash == self._last_image_hash:
                logger.info("Image unchanged, skipping display writes")
                return {
                    "preprocess_ms": 0,
                    "display_ms": 0,
                    "display_driver": self.display.__class__.__name__,
                }
            previous_hash = self._last_image_hash
            self._last_image_hash = image_hash

        try:
            preprocess_t0 = perf_counter()
            # Save the raw image
            logger.info(f"Saving image to {self.device_config.current_image_file}")
            try:
                image.save(self.device_config.current_image_file, optimize=True)
            except (OSError, ValueError, RuntimeError):
                logger.exception("Failed to save current image preview")

            # Resize and adjust orientation
            orientation = self.device_config.get_config("orientation")
            image = change_orientation(
                image, orientation if isinstance(orientation, str) else "horizontal"
            )
            image = cast(Any, resize_image)(
                image, self.device_config.get_resolution(), image_settings
            )
            if self.device_config.get_config("inverted_image"):
                image = image.rotate(180)
            image = cast(Any, apply_image_enhancement)(
                image, self.device_config.get_config("image_settings")
            )
            try:
                image.save(self.device_config.processed_image_file, optimize=True)
            except (OSError, ValueError, RuntimeError):
                logger.exception("Failed to save processed image preview")
            self._save_history_entry(image, history_meta=history_meta)
            preprocess_ms = int((perf_counter() - preprocess_t0) * 1000)

            # JTN-786: signal the caller that the image is safely on disk
            # BEFORE the slow SPI write below.  On a Pi Zero 2 W driving an
            # Inky 7.3" Impression the display_image() call below can take
            # ~27s — long enough to blow the manual-update 60s cap when
            # combined with preprocessing.  Firing this callback early lets
            # ``manual_update`` return HTTP 200 while the hardware finishes
            # asynchronously.
            if on_image_saved is not None:
                try:
                    on_image_saved({"preprocess_ms": preprocess_ms})
                except Exception:
                    logger.exception("on_image_saved callback failed")

            # Pass to the concrete instance to render to the device.
            display_t0 = perf_counter()
            self.display.display_image(image, image_settings)
            display_ms = int((perf_counter() - display_t0) * 1000)
        except Exception:
            # Restore the previous hash so the same image can be retried on the
            # next refresh cycle rather than being permanently skipped.
            with self._hash_lock:
                self._last_image_hash = previous_hash
            raise

        return {
            "preprocess_ms": preprocess_ms,
            "display_ms": display_ms,
            "display_driver": self.display.__class__.__name__,
        }

    def display_preprocessed_image(self, image_path: str) -> dict[str, int | str]:
        """Display an already-processed image file without applying transforms again."""
        from PIL import Image

        with Image.open(image_path) as img:
            image = img.copy()
        preprocess_t0 = perf_counter()
        image.save(self.device_config.current_image_file, optimize=True)
        image.save(self.device_config.processed_image_file, optimize=True)
        preprocess_ms = int((perf_counter() - preprocess_t0) * 1000)
        display_t0 = perf_counter()
        self.display.display_image(image, [])
        display_ms = int((perf_counter() - display_t0) * 1000)
        # Clear the dedup hash so the next regular refresh is not skipped
        # because it still matches the pre-history image hash (JTN-236).
        with self._hash_lock:
            self._last_image_hash = None
        return {
            "preprocess_ms": preprocess_ms,
            "display_ms": display_ms,
            "display_driver": self.display.__class__.__name__,
        }
