"""Renders a composite ("multi-region") screen: several plugins, one canvas.

Ported from the InkyPi-Layout prototype (github.com/cartagena/InkyPi-Layout),
which built this as a third-party plugin. Here it is a native rendering path
dispatched from refresh_task/executor.py and worker.py whenever a
PluginInstance's plugin_id is model.COMPOSITE_PLUGIN_ID — see
model.is_composite_instance and the ADR-0001 subprocess-isolation notes for
why this still runs as a single opaque unit rather than one subprocess per
region.
"""

import hashlib
import json
import logging
import os
import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from PIL import Image

from plugins.plugin_registry import get_plugin_instance

logger = logging.getLogger(__name__)

REQUIRED_REGION_KEYS = ("plugin_id", "x", "y", "w", "h")

#: Orphaned region cache files (left behind when a region is moved, resized,
#: reconfigured, or deleted) are swept once their mtime passes this age. Age
#: rather than "not in the current region set" because several composite
#: screens share one cache directory — set-based pruning would have each
#: screen delete the others' still-live entries on every refresh.
CACHE_MAX_AGE_DAYS = 14

#: Subdirectory of plugin_image_dir holding per-region cached renders.
CACHE_DIR_NAME = "composite"


class _RegionDeviceConfig:
    """DeviceConfigLike proxy that reports a region's (w, h) as the resolution.

    Wraps the real device_config so a child plugin's own internal layout logic
    (font sizes, wrapping, spacing) adapts to the region's actual pixel size
    instead of rendering full-screen and getting cropped down. Orientation is
    pinned to "horizontal" so BasePlugin.get_oriented_dimensions() — which
    some plugins call instead of get_resolution() directly — doesn't swap
    width/height based on the *device's* orientation setting; the region's
    w/h is already the exact size the child should render at. Everything
    else (timezone, API keys via load_env_key, plugin_image_dir, etc.)
    delegates straight through to the real device_config.
    """

    def __init__(self, device_config: Any, width: int, height: int) -> None:
        self._device_config = device_config
        self._width = width
        self._height = height

    def get_resolution(self) -> tuple[int, int]:
        return (self._width, self._height)

    def get_config(self, key: str | None = None, default: Any = None) -> Any:
        if key == "orientation":
            return "horizontal"
        return self._device_config.get_config(key, default)

    def load_env_key(self, key: str) -> str | None:
        return cast("str | None", self._device_config.load_env_key(key))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._device_config, name)


class CompositeScreenRenderer:
    """Renders a composite screen's regions onto one canvas.

    Constructed with the region list from a composite PluginInstance's
    settings["regions"]. Implements the same generate_image(settings,
    device_config) shape as a plugin's BasePlugin.generate_image so it can be
    handed to RefreshAction.execute() (actions.PluginLike) in place of a
    plugin resolved via plugins.plugin_registry — see the dispatch branches
    in executor.py/worker.py. `settings` is accepted but unused: region data
    already came from the PluginInstance that constructed this renderer.
    """

    def __init__(self, regions: list[dict[str, Any]]) -> None:
        self._raw_regions = regions

    def generate_image(self, settings: Any, device_config: Any) -> Image.Image:
        # BasePlugin and ImageDraw are only needed once a composite screen is
        # actually rendered, not at import time — executor.py/worker.py
        # import this module unconditionally at InkyPi startup, and
        # BasePlugin's own import chain (jinja2, screenshot/image-loader
        # tooling) is exactly the "heavy module at startup" cost
        # test_lazy_imports.py guards against. Mirrors the same lazy-import
        # pattern utils/fallback_image.py already uses for ImageDraw.
        from PIL import ImageDraw

        from plugins.base_plugin.base_plugin import BasePlugin

        regions = self._parse_regions(self._raw_regions)
        if not regions:
            raise RuntimeError("At least one region must be configured.")

        canvas_w, canvas_h = BasePlugin.get_oriented_dimensions(device_config)

        for region in regions:
            error = self._validate_region(region, canvas_w, canvas_h)
            if error:
                raise RuntimeError(error)
            if not device_config.get_plugin(region["plugin_id"]):
                raise RuntimeError(
                    f"Plugin '{region['plugin_id']}' is not installed/registered."
                )

        canvas = Image.new("RGB", (canvas_w, canvas_h), "white")
        draw = ImageDraw.Draw(canvas)
        now = datetime.now(UTC)
        self._prune_cache_dir(device_config, now)

        for index, region in enumerate(regions):
            region_image = self._render_region(region, index, device_config, now)
            canvas.paste(region_image, (region["x"], region["y"]))
            draw.rectangle(
                [
                    region["x"],
                    region["y"],
                    region["x"] + region["w"] - 1,
                    region["y"] + region["h"] - 1,
                ],
                outline="black",
                width=1,
            )

        return canvas

    # ---- region rendering / per-region caching ----
    #
    # This cache only protects *child plugins* from being invoked (and thus
    # hitting their upstream APIs) more often than refresh_minutes calls for.
    # It does NOT reduce how often the physical e-paper panel itself
    # refreshes — that cadence is controlled entirely by this composite
    # instance's own playlist refresh interval. generate_image() always
    # recomposites and returns a full canvas on every call; only the
    # expensive child generate_image() call is what gets skipped when a
    # region's cache is still fresh.
    #
    # The cache is *entirely* on-disk: a PNG per region under
    # <plugin_image_dir>/composite/, with the file's own mtime as the "cached
    # at" timestamp. Nothing about it is kept in `settings`. That's not a
    # style preference — InkyPi runs generate_image() in a subprocess by
    # default (INKYPI_PLUGIN_ISOLATION), so `settings` arrives as a pickled
    # copy and anything written back into it is discarded when the child
    # exits.

    def _render_region(
        self,
        region: dict[str, Any],
        index: int,
        device_config: Any,
        now: datetime,
    ) -> Image.Image:
        w, h = region["w"], region["h"]
        cache_path = self._region_cache_path(region, index, device_config)
        refresh_minutes = region.get("refresh_minutes")

        if refresh_minutes and cache_path:
            cached_at = self._cache_timestamp(cache_path)
            if cached_at and now - cached_at < timedelta(minutes=refresh_minutes):
                cached_image = self._load_cached_image(cache_path, w, h)
                if cached_image is not None:
                    return cached_image

        try:
            image = self._call_child_plugin(region, device_config)
        except Exception as e:
            logger.error(
                "Composite region %d ('%s') failed to render: %s",
                index,
                region["plugin_id"],
                e,
            )
            # Prefer a stale cached image over a blank error box — the rest
            # of the composite is still useful even if one region's data
            # source is temporarily unavailable.
            fallback = self._load_cached_image(cache_path, w, h)
            if fallback is not None:
                logger.warning(
                    "Composite region %d ('%s') reusing stale cached image "
                    "after render failure.",
                    index,
                    region["plugin_id"],
                )
                return fallback
            return self._render_error_placeholder(region, str(e))

        if image.size != (w, h):
            logger.warning(
                "Plugin '%s' returned image %s, expected %s; resizing.",
                region["plugin_id"],
                image.size,
                (w, h),
            )
            image = image.resize((w, h))

        self._store_cache(cache_path, image)
        return image

    def _call_child_plugin(
        self, region: dict[str, Any], device_config: Any
    ) -> Image.Image:
        plugin_id = region["plugin_id"]
        plugin_config = device_config.get_plugin(plugin_id)
        if not plugin_config:
            raise RuntimeError(f"Plugin '{plugin_id}' is not installed/registered.")

        child = get_plugin_instance(plugin_config)
        scoped_device_config = _RegionDeviceConfig(
            device_config, region["w"], region["h"]
        )
        region_settings = region.get("settings") or {}
        image: Image.Image = child.generate_image(region_settings, scoped_device_config)
        return image.convert("RGB")

    def _region_cache_key(self, region: dict[str, Any], index: int) -> str:
        payload = json.dumps(
            {
                "plugin_id": region["plugin_id"],
                "x": region["x"],
                "y": region["y"],
                "w": region["w"],
                "h": region["h"],
                "settings": region.get("settings") or {},
            },
            sort_keys=True,
            default=str,
        )
        digest = hashlib.sha1(
            payload.encode("utf-8"), usedforsecurity=False
        ).hexdigest()[:10]
        # The digest alone identifies the region; plugin_id is in the filename
        # purely so the cache directory is readable. Strip it to the
        # characters InkyPi's own plugin-id pattern allows anyway, so a
        # hand-edited region config can never steer this into a path outside
        # the cache dir.
        safe_plugin_id = re.sub(r"[^A-Za-z0-9_]", "", region["plugin_id"])[:40]
        return f"{index}_{safe_plugin_id}_{digest}"

    def _cache_dir(self, device_config: Any) -> str | None:
        base = getattr(device_config, "plugin_image_dir", None)
        if not base:
            return None
        return os.path.join(base, CACHE_DIR_NAME)

    def _region_cache_path(
        self, region: dict[str, Any], index: int, device_config: Any
    ) -> str | None:
        cache_dir = self._cache_dir(device_config)
        if cache_dir is None:
            return None
        return os.path.join(cache_dir, f"{self._region_cache_key(region, index)}.png")

    @staticmethod
    def _store_cache(cache_path: str | None, image: Image.Image) -> None:
        if cache_path is None:
            return
        try:
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            image.save(cache_path, format="PNG")
        except OSError as e:
            logger.warning("Composite: failed to write region cache file: %s", e)

    @staticmethod
    def _cache_timestamp(cache_path: str) -> datetime | None:
        """Return when *cache_path* was last written, as an aware UTC datetime."""
        try:
            return datetime.fromtimestamp(os.path.getmtime(cache_path), UTC)
        except OSError:
            return None

    @staticmethod
    def _load_cached_image(
        cache_path: str | None, width: int, height: int
    ) -> Image.Image | None:
        if not cache_path or not os.path.isfile(cache_path):
            return None
        try:
            with Image.open(cache_path) as cached:
                cached.load()
                if cached.size != (width, height):
                    return None
                return cached.convert("RGB")
        except Exception:
            return None

    def _prune_cache_dir(self, device_config: Any, now: datetime) -> None:
        """Delete region cache files older than CACHE_MAX_AGE_DAYS.

        Every edit to a region's geometry or settings changes its cache key
        and so orphans the previous file; without this the cache directory
        grows for the life of the install. Pruning by age rather than by "not
        referenced by the regions I just rendered" is deliberate — multiple
        composite screens share this one directory, and a set-difference
        sweep would have each screen delete the others' still-live entries on
        every refresh.
        """
        cache_dir = self._cache_dir(device_config)
        if cache_dir is None or not os.path.isdir(cache_dir):
            return
        cutoff = now - timedelta(days=CACHE_MAX_AGE_DAYS)
        try:
            with os.scandir(cache_dir) as entries:
                for entry in entries:
                    if not entry.is_file() or not entry.name.endswith(".png"):
                        continue
                    cached_at = self._cache_timestamp(entry.path)
                    if cached_at is None or cached_at >= cutoff:
                        continue
                    try:
                        os.remove(entry.path)
                    except OSError as e:
                        logger.warning(
                            "Composite: failed to prune stale cache file %s: %s",
                            entry.path,
                            e,
                        )
        except OSError as e:
            logger.warning("Composite: failed to scan region cache directory: %s", e)

    @staticmethod
    def _render_error_placeholder(region: dict[str, Any], message: str) -> Image.Image:
        from PIL import ImageDraw

        w, h = region["w"], region["h"]
        image = Image.new("RGB", (w, h), "#f0f0f0")
        draw = ImageDraw.Draw(image)
        # The reason goes on the panel as well as in the log: this box is
        # often the only symptom an operator sees, and "unavailable" alone
        # doesn't distinguish a missing API key from an upstream outage.
        draw.text(
            (6, 6),
            f"{region['plugin_id']}\nunavailable\n{message[:120]}",
            fill="black",
        )
        return image

    # ---- region config parsing / validation ----

    @staticmethod
    def _parse_regions(raw_regions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        parsed: list[dict[str, Any]] = []
        for i, region in enumerate(raw_regions):
            if not isinstance(region, dict):
                raise RuntimeError(f"Region {i} must be a JSON object.")

            missing = [k for k in REQUIRED_REGION_KEYS if k not in region]
            if missing:
                raise RuntimeError(
                    f"Region {i} is missing required field(s): {', '.join(missing)}."
                )

            plugin_id = region["plugin_id"]
            if not isinstance(plugin_id, str) or not plugin_id:
                raise RuntimeError(f"Region {i} has an invalid plugin_id.")

            try:
                x, y, w, h = (
                    int(region["x"]),
                    int(region["y"]),
                    int(region["w"]),
                    int(region["h"]),
                )
            except (TypeError, ValueError) as e:
                raise RuntimeError(f"Region {i} has non-integer x/y/w/h.") from e

            refresh_minutes = region.get("refresh_minutes")
            if refresh_minutes is not None:
                try:
                    refresh_minutes = int(refresh_minutes)
                except (TypeError, ValueError) as e:
                    raise RuntimeError(
                        f"Region {i} has a non-integer refresh_minutes."
                    ) from e
                if refresh_minutes < 0:
                    raise RuntimeError(f"Region {i} has a negative refresh_minutes.")

            region_settings = region.get("settings")
            if region_settings is None:
                region_settings = {}
            if not isinstance(region_settings, dict):
                raise RuntimeError(f"Region {i}'s settings must be a JSON object.")

            parsed.append(
                {
                    "plugin_id": plugin_id,
                    "x": x,
                    "y": y,
                    "w": w,
                    "h": h,
                    "settings": region_settings,
                    "refresh_minutes": refresh_minutes,
                }
            )

        return parsed

    @staticmethod
    def validate_region_shape(region: Mapping[str, Any]) -> str | None:
        """Checks that hold at any resolution — usable at save time, before a
        real device_config/canvas size is available."""
        x, y, w, h = region["x"], region["y"], region["w"], region["h"]
        plugin_id = region["plugin_id"]
        if w <= 0 or h <= 0:
            return f"Region for '{plugin_id}' must have positive width and height."
        if x < 0 or y < 0:
            return f"Region for '{plugin_id}' has a negative x or y."
        return None

    @classmethod
    def _validate_region(
        cls, region: dict[str, Any], canvas_width: int, canvas_height: int
    ) -> str | None:
        shape_error = cls.validate_region_shape(region)
        if shape_error:
            return shape_error
        x, y, w, h = region["x"], region["y"], region["w"], region["h"]
        plugin_id = region["plugin_id"]
        if x + w > canvas_width or y + h > canvas_height:
            return (
                f"Region for '{plugin_id}' at x={x}, y={y}, w={w}, h={h} exceeds the "
                f"{canvas_width}x{canvas_height} canvas."
            )
        return None


def resolve_composite_renderer(refresh_action: Any) -> CompositeScreenRenderer:
    """Build a renderer for a composite PlaylistRefresh action.

    Called from executor.py/worker.py's plugin-resolution step in place of
    plugins.plugin_registry.get_plugin_instance whenever the refresh
    action's plugin id is model.COMPOSITE_PLUGIN_ID. Regions live in the
    PluginInstance's own settings["regions"] (see model.COMPOSITE_PLUGIN_ID's
    docstring for why no PluginInstance field was added for this).
    """
    plugin_instance = getattr(refresh_action, "plugin_instance", None)
    settings = getattr(plugin_instance, "settings", None)
    regions = settings.get("regions") if isinstance(settings, Mapping) else None
    return CompositeScreenRenderer(list(regions) if isinstance(regions, list) else [])


def parse_regions(raw_regions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parse and structurally validate a raw regions list.

    Public entry point for callers outside this module (the
    add_composite_screen route) that need the same required-field/type
    checks CompositeScreenRenderer.generate_image runs, before a
    PluginInstance is even saved. Raises RuntimeError with a user-facing
    message on the first invalid region — same contract as the private
    method it wraps.
    """
    return CompositeScreenRenderer._parse_regions(raw_regions)
