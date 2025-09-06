import logging
import os
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from utils.app_utils import get_fonts, resolve_path
from utils.image_utils import take_screenshot_html

logger = logging.getLogger(__name__)

PLUGINS_DIR = resolve_path("plugins")
BASE_PLUGIN_DIR = os.path.join(PLUGINS_DIR, "base_plugin")
BASE_PLUGIN_RENDER_DIR = os.path.join(BASE_PLUGIN_DIR, "render")

FRAME_STYLES = [
    {"name": "None", "icon": "frames/blank.png"},
    {"name": "Corner", "icon": "frames/corner.png"},
    {"name": "Top and Bottom", "icon": "frames/top_and_bottom.png"},
    {"name": "Rectangle", "icon": "frames/rectangle.png"},
]


class BasePlugin:
    """Base class for all plugins."""

    def __init__(self, config, **dependencies):
        self.config = config

        self.render_dir = self.get_plugin_dir("render")
        # Always initialize Jinja environment so plugins without their own
        # render/ directory can still render using the base plugin templates.
        search_paths = [BASE_PLUGIN_RENDER_DIR]
        if os.path.exists(self.render_dir):
            # If the plugin provides its own templates, prioritize those first.
            search_paths.insert(0, self.render_dir)
        loader = FileSystemLoader(search_paths)
        self.env = Environment(
            loader=loader, autoescape=select_autoescape(["html", "xml"])
        )
        # Enable template auto-reload for development convenience
        try:
            self.env.auto_reload = True
        except Exception:
            pass

    def generate_image(self, settings, device_config):
        raise NotImplementedError("generate_image must be implemented by subclasses")

    def get_plugin_id(self):
        return self.config.get("id")

    def get_plugin_dir(self, path=None):
        plugin_dir = os.path.join(PLUGINS_DIR, self.get_plugin_id())
        if path:
            plugin_dir = os.path.join(plugin_dir, path)
        return plugin_dir

    def generate_settings_template(self):
        template_params = {"settings_template": "base_plugin/settings.html"}

        settings_path = self.get_plugin_dir("settings.html")
        if Path(settings_path).is_file():
            template_params["settings_template"] = (
                f"{self.get_plugin_id()}/settings.html"
            )

        template_params["frame_styles"] = FRAME_STYLES  # type: ignore[assignment]
        return template_params

    def render_image(self, dimensions, html_file, css_file=None, template_params=None):
        if template_params is None:
            template_params = {}
        # load the base plugin and current plugin css files
        css_files = [os.path.join(BASE_PLUGIN_RENDER_DIR, "plugin.css")]
        if css_file:
            plugin_css = os.path.join(self.render_dir, css_file)
            css_files.append(plugin_css)

        template_params["style_sheets"] = css_files
        template_params["width"] = dimensions[0]
        template_params["height"] = dimensions[1]
        template_params["font_faces"] = get_fonts()

        # load and render the given html template
        template = self.env.get_template(html_file)
        rendered_html = template.render(template_params)

        image = take_screenshot_html(rendered_html, dimensions)
        if image is None:
            logger.error(
                "Rendering HTML to image returned None. Check screenshot backend."
            )
            raise RuntimeError("Failed to render plugin image. See logs for details.")
        return image
