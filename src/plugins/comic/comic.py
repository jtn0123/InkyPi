import logging
from collections.abc import Mapping
from typing import Any, cast

from PIL import Image, ImageDraw
from PIL.Image import Image as ImageType
from PIL.ImageFont import ImageFont

from plugins.base_plugin.base_plugin import BasePlugin
from plugins.base_plugin.settings_schema import field, option, row, schema, section
from utils.app_utils import get_font

from .comic_parser import COMIC_LABELS, COMICS, get_panel

logger = logging.getLogger(__name__)


class Comic(BasePlugin):
    def build_settings_schema(self) -> dict[str, object]:
        schema_payload: dict[str, object] = schema(
            section(
                "Source",
                row(
                    field(
                        "comic",
                        "select",
                        label="Comic",
                        default="XKCD",
                        options=[
                            option(comic, COMIC_LABELS.get(comic, comic))
                            for comic in COMICS
                        ],
                    ),
                    field(
                        "fontSize",
                        "select",
                        label="Caption Size",
                        default="14",
                        options=[
                            option("12", "12"),
                            option("14", "14"),
                            option("16", "16"),
                            option("18", "18"),
                            option("20", "20"),
                        ],
                    ),
                ),
                field(
                    "titleCaption",
                    "checkbox",
                    label="Show Title and Caption",
                    hint="Display the comic title at the top and caption at the bottom when available.",
                    submit_unchecked=True,
                    checked_value="true",
                    unchecked_value="false",
                ),
            )
        )
        return schema_payload

    def generate_settings_template(self) -> dict[str, object]:
        template_params = super().generate_settings_template()
        settings_template: dict[str, object] = template_params
        template_params["comics"] = list(COMICS)
        return settings_template

    def generate_image(
        self, settings: Mapping[str, Any], device_config: Any
    ) -> ImageType:
        logger.info("=== Comic Plugin: Starting image generation ===")

        comic = settings.get("comic")
        if not isinstance(comic, str) or comic not in COMICS:
            comic = "XKCD"

        logger.info(f"Fetching comic: {comic}")

        is_caption = settings.get("titleCaption") == "true"
        caption_font_size = settings.get("fontSize")

        logger.debug(
            f"Settings: show_caption={is_caption}, font_size={caption_font_size}"
        )

        logger.debug("Parsing comic panel...")
        comic_panel = get_panel(comic)
        logger.info(f"Comic panel URL: {comic_panel.get('image_url', 'Unknown')}")

        if comic_panel.get("title"):
            logger.debug(f"Comic title: {comic_panel['title']}")
        if comic_panel.get("caption"):
            logger.debug(f"Comic caption: {comic_panel['caption']}")

        dimensions = self.get_oriented_dimensions(device_config)

        width, height = dimensions

        logger.debug("Composing comic image with captions...")
        image = self._compose_image(
            comic_panel, is_caption, caption_font_size, width, height
        )

        logger.info("=== Comic Plugin: Image generation complete ===")
        return image

    def _compose_image(
        self,
        comic_panel: Mapping[str, str],
        is_caption: bool,
        caption_font_size: str | None,
        width: int,
        height: int,
    ) -> ImageType:
        # Use adaptive loader for memory-efficient processing
        # Note: Comic images are usually reasonable size, but still benefit from optimization
        image_loader = cast(Any, self.image_loader)
        img = image_loader.from_url(
            comic_panel["image_url"],
            dimensions=(width, height),
            resize=False,  # We'll handle custom sizing below
        )

        if not img:
            raise RuntimeError("Failed to load comic image")

        with img:
            background = Image.new("RGB", (width, height), "white")
            font_size = int(caption_font_size) if caption_font_size else 20
            font_loader = cast(Any, get_font)
            font = font_loader("Jost", font_size=font_size)
            draw = ImageDraw.Draw(background)
            top_padding, bottom_padding = 0, 0

            if is_caption:
                if comic_panel["title"]:
                    lines, wrapped_text = self._wrap_text(
                        comic_panel["title"], font, width
                    )
                    draw.multiline_text(
                        (width // 2, 0),
                        wrapped_text,
                        font=font,
                        fill="black",
                        anchor="ma",
                    )
                    top_padding = font.getbbox(wrapped_text)[3] * lines + 1

                if comic_panel["caption"]:
                    lines, wrapped_text = self._wrap_text(
                        comic_panel["caption"], font, width
                    )
                    draw.multiline_text(
                        (width // 2, height),
                        wrapped_text,
                        font=font,
                        fill="black",
                        anchor="md",
                    )
                    bottom_padding = font.getbbox(wrapped_text)[3] * lines + 1

            scale = min(
                width / img.width, (height - top_padding - bottom_padding) / img.height
            )
            new_size = (int(img.width * scale), int(img.height * scale))
            img = img.resize(new_size, Image.LANCZOS)

            y_middle = (height - img.height) // 2
            y_top_bound = top_padding
            y_bottom_bound = height - img.height - bottom_padding

            x = (width - img.width) // 2
            y = min(max(y_middle, y_top_bound), y_bottom_bound)

            background.paste(img, (x, y))

            return background

    def _wrap_text(self, text: str, font: ImageFont, width: int) -> tuple[int, str]:
        lines = []
        words = text.split()[::-1]

        while words:
            line = words.pop()
            while words and font.getbbox(line + " " + words[-1])[2] < width:
                line += " " + words.pop()
            lines.append(line)

        return len(lines), "\n".join(lines)
