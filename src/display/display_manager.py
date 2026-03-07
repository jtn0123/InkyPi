import fnmatch
import json
import logging
import os
from datetime import datetime

from display.mock_display import MockDisplay
from utils.image_utils import apply_image_enhancement, change_orientation, resize_image

logger = logging.getLogger(__name__)

# Try to import hardware displays, but don't fail if they're not available
try:
    from display.inky_display import InkyDisplay
except ImportError:
    InkyDisplay = None
    logger.info("Inky display not available, hardware support disabled")

try:
    from display.waveshare_display import WaveshareDisplay
except ImportError:
    WaveshareDisplay = None
    logger.info("Waveshare display not available, hardware support disabled")

class DisplayManager:

    """Manages the display and rendering of images."""

    def __init__(self, device_config):

        """
        Initializes the display manager and selects the correct display type 
        based on the configuration.

        Args:
            device_config (object): Configuration object containing display settings.

        Raises:
            ValueError: If an unsupported display type is specified.
        """
        
        self.device_config = device_config
     
        display_type = device_config.get_config("display_type", default="inky")

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
    _history_count_estimate = None

    def _prune_history(self, history_dir):
        """Remove oldest history entries when the total exceeds HISTORY_MAX_ENTRIES.

        Uses an in-memory count estimate to skip the directory scan when the
        count is clearly below the limit.  The estimate is refreshed whenever
        an actual scan is performed.
        """
        if (
            self._history_count_estimate is not None
            and self._history_count_estimate < self.HISTORY_MAX_ENTRIES
        ):
            self._history_count_estimate += 1
            return
        try:
            png_files = sorted(
                (f for f in os.listdir(history_dir) if f.endswith(".png")),
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
            logger.info("Pruned %d old history entries (max %d)", excess, self.HISTORY_MAX_ENTRIES)
        except OSError:
            logger.debug("Could not prune history directory", exc_info=True)

    def _save_history_entry(self, processed_image, history_meta=None):
        """Persist a processed image snapshot and optional JSON sidecar metadata."""
        history_dir = getattr(self.device_config, "history_image_dir", None)
        if not history_dir:
            return
        try:
            os.makedirs(history_dir, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            base_name = f"display_{ts}"
            png_path = os.path.join(history_dir, f"{base_name}.png")
            # Avoid clobbering snapshots generated in the same second.
            if os.path.exists(png_path):
                suffix = datetime.now().strftime("%f")
                base_name = f"{base_name}_{suffix}"
                png_path = os.path.join(history_dir, f"{base_name}.png")

            processed_image.save(png_path, optimize=True)
        except (OSError, ValueError, RuntimeError):
            logger.exception("Failed to save history snapshot image")
            return
        try:
            meta_payload = dict(history_meta or {})
            meta_payload.setdefault("refresh_time", datetime.now().isoformat())
            with open(
                os.path.join(history_dir, f"{base_name}.json"),
                "w",
                encoding="utf-8",
            ) as fh:
                json.dump(meta_payload, fh)
        except (OSError, TypeError, ValueError):
            logger.exception("Failed to persist history metadata for %s", base_name)
        self._prune_history(history_dir)

    def display_image(self, image, image_settings=None, history_meta=None):

        """
        Delegates image rendering to the appropriate display instance.

        Args:
            image (PIL.Image): The image to be displayed.
            image_settings (list, optional): List of settings to modify image rendering.

        Raises:
            ValueError: If no valid display instance is found.
        """
        if image_settings is None:
            image_settings = []

        if not hasattr(self, "display"):
            raise ValueError("No valid display instance initialized.")
        
        # Save the raw image
        logger.info(f"Saving image to {self.device_config.current_image_file}")
        try:
            image.save(self.device_config.current_image_file, optimize=True)
        except (OSError, ValueError, RuntimeError):
            logger.exception("Failed to save current image preview")

        # Resize and adjust orientation
        image = change_orientation(
            image, self.device_config.get_config("orientation")
        )
        image = resize_image(
            image, self.device_config.get_resolution(), image_settings
        )
        if self.device_config.get_config("inverted_image"):
            image = image.rotate(180)
        image = apply_image_enhancement(
            image, self.device_config.get_config("image_settings")
        )
        try:
            image.save(self.device_config.processed_image_file, optimize=True)
        except (OSError, ValueError, RuntimeError):
            logger.exception("Failed to save processed image preview")
        self._save_history_entry(image, history_meta=history_meta)

        # Pass to the concrete instance to render to the device.
        self.display.display_image(image, image_settings)

    def display_preprocessed_image(self, image_path):
        """Display an already-processed image file without applying transforms again."""
        from PIL import Image

        with Image.open(image_path) as img:
            image = img.copy()
        image.save(self.device_config.current_image_file, optimize=True)
        image.save(self.device_config.processed_image_file, optimize=True)
        self.display.display_image(image, [])
