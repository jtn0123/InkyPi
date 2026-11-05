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
        image_loader = self.image_loader
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
            # The size setting is in pixels for an 800x480 panel; scale it up
            # on bigger panels, where a fixed 20px caption was unreadable.
            font_size = max(1, round(font_size * max(1.0, min(width, height) / 480)))
            font_loader = cast(Any, get_font)
            font = font_loader("Jost", font_size=font_size)
            draw = ImageDraw.Draw(background)
            top_padding, bottom_padding = 0, 0
            # Captions used to run flush to the panel edges.
            margin = max(2, min(width, height) // 60)
            text_width = max(1, width - 2 * margin)
            # Each text block may take at most a quarter of the panel, so the
            # comic itself always keeps room. Uncapped, a long caption on a
            # small panel left no height for the comic and PIL raised.
            max_block_height = height // 4

            if is_caption:
                if comic_panel["title"]:
                    wrapped_text, block_height = self._fit_text_block(
                        draw, comic_panel["title"], font, text_width, max_block_height
                    )
                    if wrapped_text:
                        draw.multiline_text(
                            (width // 2, margin // 2),
                            wrapped_text,
                            font=font,
                            fill="black",
                            anchor="ma",
                            align="center",
                        )
                        top_padding = block_height + margin

                if comic_panel["caption"]:
                    wrapped_text, block_height = self._fit_text_block(
                        draw, comic_panel["caption"], font, text_width, max_block_height
                    )
                    if wrapped_text:
                        draw.multiline_text(
                            (width // 2, height - margin // 2),
                            wrapped_text,
                            font=font,
                            fill="black",
                            anchor="md",
                            align="center",
                        )
                        bottom_padding = block_height + margin

            available_height = max(1, height - top_padding - bottom_padding)
            scale = min(width / img.width, available_height / img.height)
            new_size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
            img = img.resize(new_size, Image.Resampling.LANCZOS)

            y_middle = (height - img.height) // 2
            y_top_bound = top_padding
            y_bottom_bound = height - img.height - bottom_padding

            x = (width - img.width) // 2
            y = min(max(y_middle, y_top_bound), y_bottom_bound)

            background.paste(img, (x, y))

            return background

    def _fit_text_block(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        font: ImageFont,
        width: int,
        max_height: int,
    ) -> tuple[str, int]:
        """Wrap *text* to *width* and drop lines that exceed *max_height*.

        Returns the wrapped text (the last kept line ends in an ellipsis when
        lines were dropped) and its rendered height. The text is empty when
        not even one line fits.
        """
        _, wrapped_text = self._wrap_text(text, font, width)
        lines = wrapped_text.split("\n")

        def block_height(candidate: list[str]) -> int:
            bbox = draw.multiline_textbbox((0, 0), "\n".join(candidate), font=font)
            return int(bbox[3] - min(bbox[1], 0))

        kept = list(lines)
        while kept and block_height(kept) > max_height:
            kept.pop()
        if not kept:
            return "", 0
        if len(kept) < len(lines):
            last = kept[-1]
            while last and font.getbbox(last + "…")[2] >= width:
                last = last[:-1].rstrip()
            kept[-1] = last + "…"
        return "\n".join(kept), block_height(kept)

    def _wrap_text(self, text: str, font: ImageFont, width: int) -> tuple[int, str]:
        lines = []
        words = text.split()[::-1]

        while words:
            line = words.pop()
            while words and font.getbbox(line + " " + words[-1])[2] < width:
                line += " " + words.pop()
            lines.append(line)

        return len(lines), "\n".join(lines)
