import logging
import os
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from utils.app_utils import get_fonts, resolve_path
from utils.image_utils import take_screenshot_html
import os
from time import perf_counter
from utils.progress import record_step, start_step, update_step, complete_step, fail_step
import base64
from PIL import Image

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

    # ---- Optional metadata hooks (for surfacing info in the web UI) ----
    def set_latest_metadata(self, metadata: dict | None):
        """Plugins may call this to provide supplemental metadata about
        the most recent render (e.g., title, date, description, source URLs).

        The refresh task can read this and persist into `RefreshInfo.plugin_meta`.
        """
        try:
            setattr(self, "_latest_metadata", metadata or None)
        except Exception:
            # Never crash plugin flow due to metadata bookkeeping
            pass

    def get_latest_metadata(self) -> dict | None:
        try:
            return getattr(self, "_latest_metadata", None)
        except Exception:
            return None

    def get_plugin_id(self):
        return self.config.get("id")

    def get_plugin_dir(self, path=None):
        plugin_dir = os.path.join(PLUGINS_DIR, self.get_plugin_id())
        if path:
            plugin_dir = os.path.join(plugin_dir, path)
        return plugin_dir

    def to_file_url(self, path: str) -> str:
        """Convert a local filesystem path to a file:// URL if needed.

        Leaves http(s), data:, and file:// URLs untouched so callers can pass
        through remote assets without change.
        """
        try:
            if path.startswith(("http://", "https://", "data:", "file://")):
                return path
            return f"file://{path}"
        except Exception:
            return path

    def path_to_data_uri(self, path: str) -> str:
        """Return a data: URI for a local file path, falling back to file:// if read fails."""
        try:
            with open(path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("ascii")
            # Best-effort mime by extension
            mime = "image/png"
            if path.endswith(".jpg") or path.endswith(".jpeg"):
                mime = "image/jpeg"
            elif path.endswith(".gif"):
                mime = "image/gif"
            return f"data:{mime};base64,{b64}"
        except Exception:
            return self.to_file_url(path)

    def generate_settings_template(self):
        template_params = {"settings_template": "base_plugin/settings.html", "style_settings": True}

        settings_path = self.get_plugin_dir("settings.html")
        if Path(settings_path).is_file():
            template_params["settings_template"] = (
                f"{self.get_plugin_id()}/settings.html"
            )

        template_params["frame_styles"] = FRAME_STYLES
        return template_params

    def render_image(self, dimensions, html_file, css_file=None, template_params=None):
        if template_params is None:
            template_params = {}
        # load the base plugin and current plugin css files
        css_files = [os.path.join(BASE_PLUGIN_RENDER_DIR, "plugin.css")]
        if css_file:
            plugin_css = os.path.join(self.render_dir, css_file)
            css_files.append(plugin_css)
        # Allow passing a list of extra CSS file names
        extra_css_files = template_params.get("extra_css_files") or []
        if isinstance(extra_css_files, list):
            for fname in extra_css_files:
                try:
                    css_files.append(os.path.join(self.render_dir, fname))
                except Exception as e:
                    logger.warning("Failed to add extra CSS file %s: %s", fname, e)

        # Convert to file:// URLs so the headless browser can load local assets.
        style_sheet_urls = [self.to_file_url(path) for path in css_files]
        template_params["style_sheets"] = style_sheet_urls
        template_params["width"] = dimensions[0]
        template_params["height"] = dimensions[1]
        # Convert font file paths to file URLs
        fonts = get_fonts()
        for f in fonts:
            try:
                f["url"] = self.to_file_url(f.get("url", ""))
            except Exception as e:
                logger.warning(
                    "Failed to convert font URL %s: %s", f.get("url", ""), e
                )
        template_params["font_faces"] = fonts

        # Optionally inline CSS when running in headless screenshot mode to avoid any
        # possible file:// loading issues on some platforms
        inline_css: list[str] = []
        for css_path in css_files:
            try:
                with open(css_path, "r", encoding="utf-8") as f:
                    inline_css.append(f.read())
            except Exception as e:
                logger.warning("Failed to read CSS file %s: %s", css_path, e)
                raise RuntimeError(f"Unable to read CSS file {css_path}") from e
        # Allow per-render extra CSS injection via plugin_settings.extra_css
        try:
            extra_css = (
                (template_params.get("plugin_settings", {}) or {}).get("extra_css")
            )
            if isinstance(extra_css, str) and extra_css.strip():
                inline_css.append(extra_css)
        except Exception as e:
            logger.warning("Failed to process extra CSS string %r: %s", extra_css, e)
            raise RuntimeError("Unable to process extra CSS string") from e
        if inline_css:
            template_params["inline_styles"] = inline_css

        # load and render the given html template
        try:
            start_step("template", f"Loading and rendering template: {html_file}")
            template = self.env.get_template(html_file)
            update_step(f"Rendering template with {len(template_params)} parameters")
            t0 = perf_counter()
            rendered_html = template.render(template_params)
            elapsed_ms = int((perf_counter() - t0) * 1000)
            complete_step(f"Template rendered successfully for {html_file} ({elapsed_ms}ms)")
            logger.info(
                "Render template complete | plugin=%s template=%s elapsed_ms=%s",
                self.get_plugin_id(),
                html_file,
                elapsed_ms,
            )
        except Exception as e:
            fail_step(f"Template rendering failed: {str(e)}")
            logger.error("Template rendering failed | plugin=%s template=%s error=%s",
                        self.get_plugin_id(), html_file, str(e))
            raise

        # Screenshot with optional timeout from environment
        try:
            start_step("screenshot", "Preparing screenshot capture")
            timeout_ms = None
            try:
                raw = os.getenv("INKYPI_SCREENSHOT_TIMEOUT_MS", "").strip()
                if raw:
                    timeout_ms = int(raw)
            except Exception:
                timeout_ms = None

            timeout_desc = f" (timeout: {timeout_ms}ms)" if timeout_ms else ""
            update_step(f"Taking screenshot of rendered HTML{timeout_desc}")

            t1 = perf_counter()
            image = take_screenshot_html(rendered_html, dimensions, timeout_ms=timeout_ms)
            elapsed_ms = int((perf_counter() - t1) * 1000)

            if image is None:
                fail_step("Screenshot capture returned None - check screenshot backend")
                logger.error(
                    "Rendering HTML to image returned None. Check screenshot backend."
                )
                try:
                    image = Image.new("RGB", (int(dimensions[0]), int(dimensions[1])), "white")
                    update_step("Created fallback white image")
                    complete_step(f"Fallback image created ({elapsed_ms}ms)")
                except Exception:
                    fail_step("Failed to create fallback image")
                    raise RuntimeError(
                        "Failed to render plugin image. See logs for details."
                    )
            else:
                complete_step(f"Screenshot captured successfully ({elapsed_ms}ms)")
                logger.info(
                    "Screenshot complete | plugin=%s timeout_ms=%s elapsed_ms=%s",
                    self.get_plugin_id(),
                    timeout_ms,
                    elapsed_ms,
                )
        except Exception as e:
            fail_step(f"Screenshot capture failed: {str(e)}")
            logger.error("Screenshot failed | plugin=%s error=%s", self.get_plugin_id(), str(e))
            raise
        return image
