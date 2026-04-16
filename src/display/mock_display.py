import logging
import os
from datetime import UTC, datetime

from PIL import Image, ImageEnhance

from .abstract_display import AbstractDisplay

logger = logging.getLogger(__name__)


class MockDisplay(AbstractDisplay):
    """Mock display for development without hardware."""

    def __init__(self, device_config):
        self.device_config = device_config
        resolution = device_config.get_resolution()
        self.width = resolution[0]
        self.height = resolution[1]
        runtime_dir = (os.getenv("INKYPI_RUNTIME_DIR") or "").strip()
        if runtime_dir:
            default_output_dir = os.path.join(runtime_dir, "mock_display_output")
        else:
            project_root = os.path.dirname(device_config.BASE_DIR)
            default_output_dir = os.path.join(
                project_root, "runtime", "mock_display_output"
            )
        self.output_dir = device_config.get_config("output_dir", default_output_dir)
        os.makedirs(self.output_dir, exist_ok=True)
        self.mock_frame_path = os.getenv(
            "INKYPI_MOCK_FRAME_PATH"
        ) or device_config.get_config("mock_frame_path", "/tmp/inkypi-mock-frame.png")
        self.mock_frame_profile = os.getenv(
            "INKYPI_MOCK_FRAME_PROFILE"
        ) or device_config.get_config("mock_frame_profile", "tricolor")
        os.makedirs(os.path.dirname(self.mock_frame_path) or ".", exist_ok=True)

    def initialize_display(self):
        """Initialize mock display (no-op for development)."""
        logger.info(f"Mock display initialized: {self.width}x{self.height}")

    def _simulate_eink_frame(self, image: Image.Image) -> Image.Image:
        """Approximate e-ink panel output for local development previews."""
        profile = str(getattr(self, "mock_frame_profile", "tricolor")).strip().lower()
        source = image.convert("RGB") if image.mode != "RGB" else image.copy()

        if profile in {"mono", "bw", "blackwhite"}:
            return (
                source.convert("L")
                .convert("1", dither=Image.Dither.FLOYDSTEINBERG)
                .convert("RGB")
            )

        if profile in {"gray", "grey", "grayscale", "greyscale"}:
            return (
                source.convert("L")
                .quantize(colors=4, dither=Image.Dither.FLOYDSTEINBERG)
                .convert("RGB")
            )

        image_settings = self.device_config.get_config("image_settings") or {}
        inky_saturation = float(image_settings.get("inky_saturation", 0.5))
        # Inky's palette saturation is commonly tuned in [0,1], while PIL
        # enhancement expects [0,2]. Keep simulation bounded and stable.
        sat = max(0.0, min(2.0, inky_saturation * 2.0))
        source = ImageEnhance.Color(source).enhance(sat)

        palette_data = [
            0,
            0,
            0,  # black
            255,
            255,
            255,  # white
            255,
            0,
            0,  # red
        ] + [0, 0, 0] * 253
        palette_img = Image.new("P", (1, 1))
        palette_img.putpalette(palette_data)
        return source.quantize(
            palette=palette_img, dither=Image.Dither.FLOYDSTEINBERG
        ).convert("RGB")

    def display_image(self, image, image_settings=None):
        if image_settings is None:
            image_settings = []
        timestamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(self.output_dir, f"display_{timestamp}.png")
        image.save(filepath, "PNG")

        # Also save as latest.png for convenience
        image.save(os.path.join(self.output_dir, "latest.png"), "PNG")
        frame_path = getattr(
            self, "mock_frame_path", os.path.join(self.output_dir, "mock_frame.png")
        )
        try:
            os.makedirs(os.path.dirname(frame_path) or ".", exist_ok=True)
            simulated = self._simulate_eink_frame(image)
            simulated.save(frame_path, "PNG")
            simulated.save(os.path.join(self.output_dir, "latest_simulated.png"), "PNG")
        except Exception:
            logger.exception("Failed to save simulated e-ink frame")
