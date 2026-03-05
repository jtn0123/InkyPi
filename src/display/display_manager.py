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

            processed_image.save(png_path)
            meta_payload = dict(history_meta or {})
            meta_payload.setdefault("refresh_time", datetime.now().isoformat())
            with open(
                os.path.join(history_dir, f"{base_name}.json"),
                "w",
                encoding="utf-8",
            ) as fh:
                json.dump(meta_payload, fh)
        except Exception:
            logger.exception("Failed to persist history snapshot")

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
        image.save(self.device_config.current_image_file)

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
        image.save(self.device_config.processed_image_file)
        self._save_history_entry(image, history_meta=history_meta)

        # Pass to the concrete instance to render to the device.
        self.display.display_image(image, image_settings)

    def display_preprocessed_image(self, image_path):
        """Display an already-processed image file without applying transforms again."""
        from PIL import Image

        with Image.open(image_path) as img:
            image = img.copy()
        image.save(self.device_config.current_image_file)
        image.save(self.device_config.processed_image_file)
        self.display.display_image(image, [])
