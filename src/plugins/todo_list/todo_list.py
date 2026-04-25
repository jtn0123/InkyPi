import logging
from collections.abc import Mapping
from typing import Any

from PIL.Image import Image as ImageType

from plugins.base_plugin.base_plugin import BasePlugin
from plugins.base_plugin.settings_schema import (
    field,
    option,
    row,
    schema,
    section,
    widget,
)

logger = logging.getLogger(__name__)

FONT_SIZES = {"x-small": 0.7, "small": 0.9, "normal": 1, "large": 1.1, "x-large": 1.3}


class TodoList(BasePlugin):
    def build_settings_schema(self) -> dict[str, object]:
        schema_payload: dict[str, object] = schema(
            section(
                "List Settings",
                row(
                    field("title", label="Title", placeholder="Tasks"),
                    field(
                        "listStyle",
                        "select",
                        label="List Style",
                        default="disc",
                        options=[
                            option("disc", "Disc (●)"),
                            option("square", "Square (◼)"),
                            option("'\\25C6  '", "Diamond (◆)"),
                            option("decimal", "Decimal"),
                            option("lower-roman", "Roman Numeral"),
                            option("lower-alpha", "Alphabetical"),
                        ],
                    ),
                    field(
                        "fontSize",
                        "select",
                        label="Font Size",
                        default="normal",
                        options=[
                            option("x-small", "Extra Small"),
                            option("small", "Small"),
                            option("normal", "Normal"),
                            option("large", "Large"),
                            option("x-large", "Extra Large"),
                        ],
                    ),
                ),
            ),
            section(
                "Lists",
                widget("todo-repeater", template="widgets/todo_repeater.html"),
            ),
        )
        return schema_payload

    def generate_settings_template(self) -> dict[str, object]:
        template_params = super().generate_settings_template()
        settings_template: dict[str, object] = template_params
        template_params["style_settings"] = True
        return settings_template

    def generate_image(
        self, settings: Mapping[str, Any], device_config: Any
    ) -> ImageType:
        dimensions = self.get_oriented_dimensions(device_config)

        titles: list[object] = list(settings.get("list-title[]", []))
        raw_lists = list(settings.get("list[]", []))
        lists: list[dict[str, object]] = []
        for title, raw_list in zip(titles, raw_lists, strict=False):
            if not isinstance(title, str):
                continue
            if not isinstance(raw_list, str):
                continue
            elements = [line for line in raw_list.split("\n") if line.strip()]
            lists.append({"title": title, "elements": elements})

        template_params: dict[str, object] = {
            "title": settings.get("title"),
            "list_style": settings.get("listStyle", "disc"),
            "font_scale": FONT_SIZES.get(settings.get("fontSize", "normal"), 1),
            "lists": lists,
            "plugin_settings": settings,
        }

        return self.render_image(
            dimensions, "todo_list.html", "todo_list.css", template_params
        )
