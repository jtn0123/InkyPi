import base64
import logging
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol, cast

from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import Image

from utils.app_utils import get_fonts, resolve_path
from utils.image_loader import AdaptiveImageLoader
from utils.image_utils import take_screenshot_html
from utils.logging_utils import redact_secrets
from utils.progress import (
    complete_step,
    fail_step,
    start_step,
    update_step,
)
from utils.sri import cdn_sri, sri_for

logger = logging.getLogger(__name__)

PLUGIN_API_VERSION = "1.0"

PLUGINS_DIR = cast(str, cast(Any, resolve_path)("plugins"))
BASE_PLUGIN_DIR = os.path.join(PLUGINS_DIR, "base_plugin")
BASE_PLUGIN_RENDER_DIR = os.path.join(BASE_PLUGIN_DIR, "render")

FRAME_STYLES = [
    {"name": "None", "icon": "frames/blank.png"},
    {"name": "Corner", "icon": "frames/corner.png"},
    {"name": "Top and Bottom", "icon": "frames/top_and_bottom.png"},
    {"name": "Rectangle", "icon": "frames/rectangle.png"},
]

# Shared set of AI provider identifiers accepted across plugins that
# support both OpenAI and Google backends.
VALID_AI_PROVIDERS = frozenset({"openai", "google"})


def validate_required_text(
    settings: Mapping[str, object], key: str, label: str
) -> str | None:
    """Return an error string if *settings[key]* is missing or blank."""
    raw_value = settings.get(key)
    value = raw_value.strip() if isinstance(raw_value, str) else ""
    if not value:
        return f"{label} is required."
    return None


def validate_provider(settings: Mapping[str, object]) -> str | None:
    """Return an error string if the provider value is not in VALID_AI_PROVIDERS."""
    provider = settings.get("provider", "openai")
    if provider not in VALID_AI_PROVIDERS:
        return f"Unsupported provider: {provider!r}"
    return None


class BasePlugin:
    """Base class for all plugins."""

    def __init__(self, config: Mapping[str, object], **dependencies: object):
        self.config = dict(config)
        self.dependencies = dependencies
        version = config.get("version")
        api_version = config.get("api_version")
        self.version: str | None = version if isinstance(version, str) else None
        self.api_version: str | None = (
            api_version if isinstance(api_version, str) else None
        )

        # Initialize adaptive image loader for device-aware image processing
        image_loader_factory = cast(Any, AdaptiveImageLoader)
        self.image_loader = image_loader_factory()

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
        # Register SRI helpers so plugin templates can use sri_for/cdn_sri
        self.env.globals["sri_for"] = sri_for
        self.env.globals["cdn_sri"] = cdn_sri
        # Enable template auto-reload for development convenience
        try:
            self.env.auto_reload = True
        except Exception:
            pass

    @staticmethod
    def get_oriented_dimensions(device_config: "DeviceConfigLike") -> tuple[int, int]:
        """Return display (width, height) adjusted for the current orientation."""
        dimensions = device_config.get_resolution()
        if device_config.get_config("orientation") == "vertical":
            dimensions = dimensions[::-1]
        return dimensions

    def generate_image(
        self, settings: Mapping[str, object], device_config: "DeviceConfigLike"
    ) -> Image.Image:
        raise NotImplementedError("generate_image must be implemented by subclasses")

    # ---- Optional metadata hooks (for surfacing info in the web UI) ----
    def set_latest_metadata(self, metadata: dict[str, object] | None) -> None:
        """Plugins may call this to provide supplemental metadata about
        the most recent render (e.g., title, date, description, source URLs).

        The refresh task can read this and persist into `RefreshInfo.plugin_meta`.
        """
        try:
            self._latest_metadata = metadata or None
        except Exception:
            # Never crash plugin flow due to metadata bookkeeping
            pass

    def get_latest_metadata(self) -> dict[str, object] | None:
        try:
            return cast(
                dict[str, object] | None, getattr(self, "_latest_metadata", None)
            )
        except Exception:
            return None

    def get_plugin_id(self) -> str:
        plugin_id = self.config.get("id")
        return plugin_id if isinstance(plugin_id, str) else ""

    def get_plugin_dir(self, path: str | None = None) -> str:
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
            if path.endswith((".jpg", ".jpeg")):
                mime = "image/jpeg"
            elif path.endswith(".gif"):
                mime = "image/gif"
            return f"data:{mime};base64,{b64}"
        except Exception:
            return self.to_file_url(path)

    def validate_settings(self, settings: Mapping[str, object]) -> str | None:
        """Validate plugin-specific settings before they are persisted.

        Plugins can override this to reject invalid settings at save time,
        before ``generate_image`` is ever called.  Return a human-readable
        error string to reject the save, or ``None`` to allow it.

        The default implementation performs no validation and always returns
        ``None``.
        """
        return None

    def build_settings_schema(self) -> dict[str, object] | None:
        """Return a declarative settings schema for shared rendering.

        Plugins can override this instead of shipping a bespoke settings.html
        when their UI can be expressed with the shared field system.
        """

    def generate_settings_template(self) -> dict[str, object]:
        template_params: dict[str, object] = {"style_settings": True}

        settings_schema = self.build_settings_schema()
        if settings_schema:
            template_params["settings_schema"] = settings_schema
        else:
            template_params["settings_template"] = "base_plugin/settings.html"

            settings_path = self.get_plugin_dir("settings.html")
            if Path(settings_path).is_file():
                template_params["settings_template"] = (
                    f"{self.get_plugin_id()}/settings.html"
                )

        template_params["frame_styles"] = FRAME_STYLES
        return template_params

    def _build_css_files(
        self, css_file: str | None, extra_css_files: Sequence[str]
    ) -> list[str]:
        """Return the ordered list of CSS file paths for this render."""
        css_files = [os.path.join(BASE_PLUGIN_RENDER_DIR, "plugin.css")]
        if css_file:
            css_files.append(os.path.join(self.render_dir, css_file))
        for fname in extra_css_files:
            try:
                css_files.append(os.path.join(self.render_dir, fname))
            except Exception as e:
                logger.warning(
                    "Failed to add extra CSS file %s: %s",
                    redact_secrets(fname),
                    redact_secrets(e),
                )
        return css_files

    def _build_inline_css(
        self, css_files: Sequence[str], template_params: Mapping[str, object]
    ) -> list[str]:
        """Read CSS files and optional extra_css from settings into an inline list."""
        inline_css: list[str] = []
        for css_path in css_files:
            try:
                with open(css_path, encoding="utf-8") as f:
                    inline_css.append(f.read())
            except Exception as e:
                safe_path = redact_secrets(css_path)
                safe_err = redact_secrets(e)
                logger.warning("Failed to read CSS file %s: %s", safe_path, safe_err)
                raise RuntimeError(f"Unable to read CSS file {safe_path}") from e
        extra_css: object = None
        try:
            plugin_settings = cast(
                dict[str, object], template_params.get("plugin_settings") or {}
            )
            extra_css = plugin_settings.get("extra_css")
            if isinstance(extra_css, str) and extra_css.strip():
                inline_css.append(extra_css)
        except Exception as e:
            safe_extra_css = redact_secrets(extra_css)
            safe_err = redact_secrets(e)
            logger.warning(
                "Failed to process extra CSS string %r: %s", safe_extra_css, safe_err
            )
            raise RuntimeError("Unable to process extra CSS string") from e
        return inline_css

    def _render_template(
        self, html_file: str, template_params: Mapping[str, object]
    ) -> str:
        """Render the Jinja2 template and return HTML string."""
        try:
            start_step("template", f"Loading and rendering template: {html_file}")
            template = self.env.get_template(html_file)
            update_step(f"Rendering template with {len(template_params)} parameters")
            t0 = perf_counter()
            rendered_html = cast(str, template.render(template_params))
            elapsed_ms = int((perf_counter() - t0) * 1000)
            complete_step(
                f"Template rendered successfully for {html_file} ({elapsed_ms}ms)"
            )
            logger.info(
                "Render template complete | plugin=%s template=%s elapsed_ms=%s",
                self.get_plugin_id(),
                html_file,
                elapsed_ms,
            )
            return rendered_html
        except Exception as e:
            fail_step(f"Template rendering failed: {str(e)}")
            logger.error(
                "Template rendering failed | plugin=%s template=%s error=%s",
                self.get_plugin_id(),
                html_file,
                str(e),
            )
            raise

    def _capture_screenshot(
        self, rendered_html: str, dimensions: tuple[int, int]
    ) -> Image.Image:
        """Take a screenshot of the rendered HTML and return a PIL Image."""
        try:
            start_step("screenshot", "Preparing screenshot capture")
            timeout_ms = self._get_screenshot_timeout()
            timeout_desc = f" (timeout: {timeout_ms}ms)" if timeout_ms else ""
            update_step(f"Taking screenshot of rendered HTML{timeout_desc}")
            t1 = perf_counter()
            screenshot_html = cast(Any, take_screenshot_html)
            image = screenshot_html(rendered_html, dimensions, timeout_ms=timeout_ms)
            elapsed_ms = int((perf_counter() - t1) * 1000)
            if image is None:
                image = self._screenshot_fallback(dimensions, elapsed_ms)
            else:
                complete_step(f"Screenshot captured successfully ({elapsed_ms}ms)")
                logger.info(
                    "Screenshot complete | plugin=%s timeout_ms=%s elapsed_ms=%s",
                    self.get_plugin_id(),
                    timeout_ms,
                    elapsed_ms,
                )
            return image
        except Exception as e:
            fail_step(f"Screenshot capture failed: {str(e)}")
            logger.error(
                "Screenshot failed | plugin=%s error=%s", self.get_plugin_id(), str(e)
            )
            raise

    @staticmethod
    def _get_screenshot_timeout() -> int | None:
        """Read INKYPI_SCREENSHOT_TIMEOUT_MS env var; return int ms or None."""
        try:
            raw = os.getenv("INKYPI_SCREENSHOT_TIMEOUT_MS", "").strip()
            return int(raw) if raw else None
        except (ValueError, TypeError):
            return None

    def _screenshot_fallback(
        self, dimensions: tuple[int, int], elapsed_ms: int
    ) -> Image.Image:
        """Create a white fallback image when the screenshot backend returns None."""
        fail_step("Screenshot capture returned None - check screenshot backend")
        logger.error("Rendering HTML to image returned None. Check screenshot backend.")
        try:
            image = Image.new("RGB", (int(dimensions[0]), int(dimensions[1])), "white")
            update_step("Created fallback white image")
            complete_step(f"Fallback image created ({elapsed_ms}ms)")
            return image
        except Exception:
            fail_step("Failed to create fallback image")
            raise RuntimeError(
                "Failed to render plugin image. See logs for details."
            ) from None

    def render_image(
        self,
        dimensions: tuple[int, int],
        html_file: str,
        css_file: str | None = None,
        template_params: dict[str, object] | None = None,
    ) -> Image.Image:
        if template_params is None:
            template_params = {}

        # Build CSS file list and inject stylesheet/dimension/font params
        raw_extra_css = template_params.get("extra_css_files")
        extra_css_files = (
            raw_extra_css
            if isinstance(raw_extra_css, Sequence)
            and not isinstance(raw_extra_css, str)
            and all(isinstance(item, str) for item in raw_extra_css)
            else []
        )
        css_files = self._build_css_files(
            css_file, cast(Sequence[str], extra_css_files)
        )
        template_params["style_sheets"] = [self.to_file_url(path) for path in css_files]
        template_params["width"] = dimensions[0]
        template_params["height"] = dimensions[1]

        fonts = cast(Any, get_fonts)()
        for f in fonts:
            try:
                if isinstance(f, dict):
                    f["url"] = self.to_file_url(f.get("url", ""))
            except Exception as e:
                url = f.get("url", "") if isinstance(f, dict) else ""
                logger.warning("Failed to convert font URL %s: %s", url, e)
        template_params["font_faces"] = fonts

        inline_css = self._build_inline_css(css_files, template_params)
        if inline_css:
            template_params["inline_styles"] = inline_css

        rendered_html = self._render_template(html_file, template_params)
        return self._capture_screenshot(rendered_html, dimensions)


class DeviceConfigLike(Protocol):
    def get_resolution(self) -> tuple[int, int]: ...

    def get_config(self, key: str, default: object = ...) -> object: ...

    def load_env_key(self, key: str) -> str | None: ...
