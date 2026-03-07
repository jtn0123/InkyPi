from plugins.base_plugin.base_plugin import BasePlugin
from plugins.base_plugin.settings_schema import field, option, row, schema, section, widget
from PIL import Image
from io import BytesIO
import requests
import logging

logger = logging.getLogger(__name__)

FONT_SIZES = {
    "x-small": 0.7,
    "small": 0.9,
    "normal": 1,
    "large": 1.1,
    "x-large": 1.3
}

class TodoList(BasePlugin):
    def build_settings_schema(self):
        return schema(
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

    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params['style_settings'] = True
        return template_params

    def generate_image(self, settings, device_config):
        dimensions = device_config.get_resolution()
        if device_config.get_config("orientation") == "vertical":
            dimensions = dimensions[::-1]

        lists = []
        titles = settings.get('list-title[]', [])
        raw_lists = settings.get('list[]', [])
        for title, raw_list in zip(titles, raw_lists):
            elements = [line for line in raw_list.split('\n') if line.strip()]
            lists.append({
                'title': title,
                'elements': elements
            })

        template_params = {
            "title": settings.get('title'),
            "list_style": settings.get('listStyle', 'disc'),
            "font_scale": FONT_SIZES.get(settings.get('fontSize', 'normal'), 1),
            "lists": lists,
            "plugin_settings": settings
        }
        
        image = self.render_image(dimensions, "todo_list.html", "todo_list.css", template_params)
        return image
