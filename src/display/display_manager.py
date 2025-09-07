import fnmatch
import logging
import os
from datetime import datetime

from display.abstract_display import AbstractDisplay
from display.mock_display import MockDisplay
from utils.image_utils import (
    apply_image_enhancement,
    change_orientation,
    resize_image,
    load_image_from_path,
)

logger = logging.getLogger(__name__)

# Try to import hardware displays, but don't fail if they're not available
try:
    from display.inky_display import InkyDisplay
except ImportError:
    logger.info("Inky display not available, hardware support disabled")

try:
    from display.waveshare_display import WaveshareDisplay
except ImportError:
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

        # Type of display device selected at runtime
        self.display: AbstractDisplay

        if display_type == "mock":
            self.display = MockDisplay(device_config)
        elif display_type == "inky":
            self.display = InkyDisplay(device_config)
        elif fnmatch.fnmatch(display_type, "epd*in*"):
            # derived from waveshare epd - we assume here that will be consistent
            # otherwise we will have to enshring the manufacturer in the
            # display_type and then have a display_model parameter.  Will leave
            # that for future use if the need arises.
            #
            # see https://github.com/waveshareteam/e-Paper
            self.display = WaveshareDisplay(device_config)
        else:
            raise ValueError(f"Unsupported display type: {display_type}")

    def display_image(self, image, image_settings=None, history_meta=None):
        """
        Delegates image rendering to the appropriate display instance.

        Args:
            image (PIL.Image): The image to be displayed.
            image_settings (list, optional): List of settings to modify image rendering.

        Raises:
            ValueError: If no valid display instance is found.
        """

        if not hasattr(self, "display"):
            raise ValueError("No valid display instance initialized.")

        # Save the image
        logger.info(f"Saving image to {self.device_config.current_image_file}")
        image.save(self.device_config.current_image_file)

        # Resize and adjust orientation
        if image_settings is None:
            image_settings = []
        # Measure preprocessing time for metrics
        from time import perf_counter
        _t0 = perf_counter()
        image = change_orientation(image, self.device_config.get_config("orientation"))
        image = resize_image(image, self.device_config.get_resolution(), image_settings)
        if self.device_config.get_config("inverted_image"):
            image = image.rotate(180)
        image = apply_image_enhancement(
            image, self.device_config.get_config("image_settings")
        )
        preprocess_ms = int((perf_counter() - _t0) * 1000)

        # Save the processed image for web preview
        try:
            image.save(self.device_config.processed_image_file)
        except Exception:
            logger.exception("Failed to save processed image preview")

        # Also persist a timestamped copy in history for browsing/reload
        try:
            from utils.time_utils import now_device_tz

            timestamp = now_device_tz(self.device_config).strftime("%Y%m%d_%H%M%S")
            history_filename = f"display_{timestamp}.png"
            history_path = os.path.join(
                self.device_config.history_image_dir, history_filename
            )
            image.save(history_path)
            logger.info("Saved history image | path=%s", history_path)
            # Write sidecar metadata if available
            try:
                if history_meta is not None:
                    import json
                    sidecar = dict(history_meta)
                    sidecar.setdefault("history_filename", history_filename)
                    sidecar.setdefault("saved_at", timestamp)
                    json_path = os.path.join(
                        self.device_config.history_image_dir,
                        f"display_{timestamp}.json",
                    )
                    with open(json_path, "w", encoding="utf-8") as fh:
                        json.dump(sidecar, fh, ensure_ascii=False, indent=2)
                    logger.info("Saved history sidecar | path=%s", json_path)
            except Exception:
                logger.exception("Failed to write history sidecar metadata")
        except Exception:
            logger.exception("Failed to save history copy of processed image")

        # Pass to the concrete instance to render to the device.
        # Render to device and capture display time for metrics
        _t1 = perf_counter()
        self.display.display_image(image, image_settings=image_settings)
        display_ms = int((perf_counter() - _t1) * 1000)

        # Persist lightweight metrics into device config's refresh_info if available
        try:
            ri = getattr(self.device_config, "refresh_info", None)
            if ri is not None:
                # Only set preprocess/display if not already present
                if getattr(ri, "preprocess_ms", None) is None:
                    ri.preprocess_ms = preprocess_ms
                if getattr(ri, "display_ms", None) is None:
                    ri.display_ms = display_ms
                # Do not write config here; the refresh loop owns writes
        except Exception:
            logger.exception("Failed to record display metrics")

    def display_preprocessed_image(self, image_path: str):
        """
        Display a previously processed image without re-processing.

        Updates the preview/current images for the web UI and delegates
        directly to the underlying display driver.
        """
        if not hasattr(self, "display"):
            raise ValueError("No valid display instance initialized.")

        # Load image using standardized helper
        image = load_image_from_path(image_path)
        if image is None:
            raise RuntimeError("Failed to load preprocessed image from path")

        # Update preview/current files for the UI
        try:
            image.save(self.device_config.processed_image_file)
            image.save(self.device_config.current_image_file)
        except Exception:
            logger.exception(
                "Failed to update preview/current image files for redisplay"
            )

        # Send directly to hardware without further processing
        self.display.display_image(image, image_settings=[])
