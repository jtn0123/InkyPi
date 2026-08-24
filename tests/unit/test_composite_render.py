"""Tests for the native composite-screen renderer (refresh_task/composite_render.py).

Child plugins are always faked here — never call a real plugin's upstream API
from this file.
"""

import copy
import os
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from PIL import Image

from refresh_task.composite_render import CACHE_MAX_AGE_DAYS, CompositeScreenRenderer


class FakeDeviceConfig:
    """Minimal DeviceConfigLike + get_plugin()/plugin_image_dir double."""

    def __init__(
        self,
        tmp_path: Path,
        plugins: dict[str, dict[str, str]],
        resolution: tuple[int, int] = (800, 480),
        orientation: str = "horizontal",
    ) -> None:
        self._resolution = resolution
        self._orientation = orientation
        self._plugins = plugins
        self.plugin_image_dir = str(tmp_path / "plugin_images")

    def get_resolution(self) -> tuple[int, int]:
        return self._resolution

    def get_config(self, key: str | None = None, default: Any = None) -> Any:
        if key == "orientation":
            return self._orientation
        return default

    def load_env_key(self, key: str) -> str | None:
        return None

    def get_plugin(self, plugin_id: str) -> dict[str, str] | None:
        return self._plugins.get(plugin_id)


class FakeColorPlugin:
    """Fake child plugin: fills its assigned region with a solid color.

    Tracks call count (class-level, keyed by plugin id) so tests can assert
    on caching/reuse behavior without touching a real plugin's API.
    """

    call_counts: dict[str, int] = {}
    fail_ids: set[str] = set()

    def __init__(self, config: dict[str, str]) -> None:
        self.config = config

    def generate_image(
        self, settings: dict[str, Any], device_config: Any
    ) -> Image.Image:
        plugin_id = self.config["id"]
        FakeColorPlugin.call_counts[plugin_id] = (
            FakeColorPlugin.call_counts.get(plugin_id, 0) + 1
        )
        if plugin_id in FakeColorPlugin.fail_ids:
            raise RuntimeError(f"fake failure for {plugin_id}")
        w, h = device_config.get_resolution()
        color = settings.get("color", "red")
        return Image.new("RGB", (w, h), color)


@pytest.fixture(autouse=True)
def _reset_fake_plugin_state() -> Iterator[None]:
    FakeColorPlugin.call_counts = {}
    FakeColorPlugin.fail_ids = set()
    yield


def _patch_get_plugin_instance() -> Any:
    return patch(
        "refresh_task.composite_render.get_plugin_instance",
        side_effect=lambda config: FakeColorPlugin(config),
    )


def _plugins_map(*ids: str) -> dict[str, dict[str, str]]:
    return {pid: {"id": pid, "class": "FakeColorPlugin"} for pid in ids}


def _as_subprocess_would(regions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return regions as they'd arrive after crossing the subprocess boundary.

    InkyPi runs generate_image() in a separate process by default
    (INKYPI_PLUGIN_ISOLATION=process), so the renderer is handed a pickled
    copy of the PluginInstance and anything it writes back is discarded when
    the child exits. Tests that reuse one long-lived regions list across
    several generate_image() calls would silently grant this renderer a
    persistence channel production doesn't actually have — deep-copying per
    call models the real boundary.
    """
    return copy.deepcopy(regions)


# ---------------------------------------------------------------------------
# Regions land at the correct pixel offsets
# ---------------------------------------------------------------------------


def test_regions_land_at_correct_pixel_offsets(tmp_path: Path) -> None:
    regions = [
        {
            "plugin_id": "fake_a",
            "x": 0,
            "y": 0,
            "w": 400,
            "h": 200,
            "settings": {"color": "red"},
        },
        {
            "plugin_id": "fake_b",
            "x": 400,
            "y": 0,
            "w": 400,
            "h": 200,
            "settings": {"color": "blue"},
        },
        {
            "plugin_id": "fake_a",
            "x": 0,
            "y": 200,
            "w": 800,
            "h": 280,
            "settings": {"color": "green"},
        },
    ]
    device_config = FakeDeviceConfig(tmp_path, _plugins_map("fake_a", "fake_b"))
    renderer = CompositeScreenRenderer(regions)

    with _patch_get_plugin_instance():
        image = renderer.generate_image({}, device_config)

    assert image.size == (800, 480)
    # Sample well inside each region (avoiding the 1px black border) to
    # confirm the right child's output landed at the right offset.
    assert image.getpixel((200, 100)) == (255, 0, 0)  # region 1 (red)
    assert image.getpixel((600, 100)) == (0, 0, 255)  # region 2 (blue)
    assert image.getpixel((400, 350)) == (0, 128, 0)  # region 3 (green)


def test_region_border_is_drawn(tmp_path: Path) -> None:
    regions = [
        {"plugin_id": "fake_a", "x": 10, "y": 10, "w": 100, "h": 100, "settings": {}}
    ]
    device_config = FakeDeviceConfig(tmp_path, _plugins_map("fake_a"))
    renderer = CompositeScreenRenderer(regions)

    with _patch_get_plugin_instance():
        image = renderer.generate_image({}, device_config)

    assert image.getpixel((10, 10)) == (0, 0, 0)
    assert image.getpixel((109, 10)) == (0, 0, 0)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_generate_image_rejects_out_of_bounds_region(tmp_path: Path) -> None:
    regions = [
        {"plugin_id": "fake_a", "x": 700, "y": 0, "w": 200, "h": 60, "settings": {}}
    ]
    device_config = FakeDeviceConfig(tmp_path, _plugins_map("fake_a"))
    renderer = CompositeScreenRenderer(regions)

    with pytest.raises(RuntimeError, match="exceeds the"):
        renderer.generate_image({}, device_config)


def test_generate_image_rejects_negative_offset(tmp_path: Path) -> None:
    regions = [
        {"plugin_id": "fake_a", "x": -5, "y": 0, "w": 100, "h": 60, "settings": {}}
    ]
    device_config = FakeDeviceConfig(tmp_path, _plugins_map("fake_a"))
    renderer = CompositeScreenRenderer(regions)

    with pytest.raises(RuntimeError, match="negative"):
        renderer.generate_image({}, device_config)


def test_generate_image_requires_at_least_one_region(tmp_path: Path) -> None:
    device_config = FakeDeviceConfig(tmp_path, {})
    renderer = CompositeScreenRenderer([])

    with pytest.raises(RuntimeError, match="At least one region"):
        renderer.generate_image({}, device_config)


def test_generate_image_rejects_unknown_plugin(tmp_path: Path) -> None:
    regions = [
        {
            "plugin_id": "does_not_exist",
            "x": 0,
            "y": 0,
            "w": 100,
            "h": 60,
            "settings": {},
        }
    ]
    device_config = FakeDeviceConfig(tmp_path, {})
    renderer = CompositeScreenRenderer(regions)

    with pytest.raises(RuntimeError, match="not installed"):
        renderer.generate_image({}, device_config)


def test_validate_region_shape_rejects_non_positive_size() -> None:
    region = {"plugin_id": "fake_a", "x": 0, "y": 0, "w": 0, "h": 60}
    error = CompositeScreenRenderer.validate_region_shape(region)
    assert error is not None
    assert "positive" in error


def test_validate_region_shape_rejects_negative_offset() -> None:
    region = {"plugin_id": "fake_a", "x": -1, "y": 0, "w": 100, "h": 60}
    error = CompositeScreenRenderer.validate_region_shape(region)
    assert error is not None
    assert "negative" in error


def test_validate_region_shape_accepts_valid_region() -> None:
    region = {"plugin_id": "fake_a", "x": 0, "y": 0, "w": 800, "h": 60}
    assert CompositeScreenRenderer.validate_region_shape(region) is None


def test_validate_region_shape_does_not_assume_an_800x480_canvas() -> None:
    """A full-screen region on a larger panel must still be savable.

    Shape validation gets no device_config, so it cannot know the real
    resolution; bounds-checking against a hardcoded default here would make
    the feature unusable on anything bigger than 800x480.
    """
    region = {"plugin_id": "fake_a", "x": 0, "y": 0, "w": 1600, "h": 1200}
    assert CompositeScreenRenderer.validate_region_shape(region) is None


# ---------------------------------------------------------------------------
# Per-region caching
# ---------------------------------------------------------------------------


def test_cached_region_skips_child_plugin_within_refresh_window(tmp_path: Path) -> None:
    regions = [
        {
            "plugin_id": "fake_a",
            "x": 0,
            "y": 0,
            "w": 100,
            "h": 60,
            "settings": {},
            "refresh_minutes": 15,
        }
    ]
    device_config = FakeDeviceConfig(tmp_path, _plugins_map("fake_a"))
    renderer = CompositeScreenRenderer(regions)

    with _patch_get_plugin_instance():
        renderer.generate_image({}, device_config)
        renderer.generate_image({}, device_config)

    assert FakeColorPlugin.call_counts["fake_a"] == 1
    assert list((tmp_path / "plugin_images" / "composite").glob("*.png"))


def test_expired_cache_re_invokes_child_plugin(tmp_path: Path) -> None:
    regions = [
        {
            "plugin_id": "fake_a",
            "x": 0,
            "y": 0,
            "w": 100,
            "h": 60,
            "settings": {},
            "refresh_minutes": 15,
        }
    ]
    device_config = FakeDeviceConfig(tmp_path, _plugins_map("fake_a"))
    renderer = CompositeScreenRenderer(regions)

    with _patch_get_plugin_instance():
        renderer.generate_image({}, device_config)
        for cached in (tmp_path / "plugin_images" / "composite").glob("*.png"):
            old = time.time() - 3600
            os.utime(cached, (old, old))
        renderer.generate_image({}, device_config)

    assert FakeColorPlugin.call_counts["fake_a"] == 2


def test_region_without_refresh_minutes_always_refreshes(tmp_path: Path) -> None:
    regions = [
        {"plugin_id": "fake_a", "x": 0, "y": 0, "w": 100, "h": 60, "settings": {}}
    ]
    device_config = FakeDeviceConfig(tmp_path, _plugins_map("fake_a"))
    renderer = CompositeScreenRenderer(regions)

    with _patch_get_plugin_instance():
        renderer.generate_image({}, device_config)
        renderer.generate_image({}, device_config)

    assert FakeColorPlugin.call_counts["fake_a"] == 2


def test_child_failure_falls_back_to_stale_cache_instead_of_raising(
    tmp_path: Path,
) -> None:
    regions = [
        {
            "plugin_id": "fake_a",
            "x": 0,
            "y": 0,
            "w": 100,
            "h": 60,
            "settings": {"color": "red"},
            "refresh_minutes": 0,
        }
    ]
    device_config = FakeDeviceConfig(tmp_path, _plugins_map("fake_a"))
    renderer = CompositeScreenRenderer(regions)

    with _patch_get_plugin_instance():
        first = renderer.generate_image({}, device_config)
        FakeColorPlugin.fail_ids.add("fake_a")
        second = renderer.generate_image({}, device_config)

    # Region content (excluding the border) should be identical: the stale
    # cached render was reused rather than a blank error placeholder.
    assert first.getpixel((50, 30)) == second.getpixel((50, 30)) == (255, 0, 0)


def test_stale_cache_files_are_pruned(tmp_path: Path) -> None:
    regions = [
        {"plugin_id": "fake_a", "x": 0, "y": 0, "w": 100, "h": 60, "settings": {}}
    ]
    device_config = FakeDeviceConfig(tmp_path, _plugins_map("fake_a"))
    renderer = CompositeScreenRenderer(regions)
    cache_dir = tmp_path / "plugin_images" / "composite"
    cache_dir.mkdir(parents=True)

    # An orphan left behind by a region that was since moved or deleted.
    orphan = cache_dir / "9_gone_deadbeef00.png"
    Image.new("RGB", (10, 10), "white").save(orphan)
    expired = time.time() - (CACHE_MAX_AGE_DAYS + 1) * 86400
    os.utime(orphan, (expired, expired))

    with _patch_get_plugin_instance():
        renderer.generate_image({}, device_config)

    assert not orphan.exists()
    # The region rendered this pass keeps its own fresh cache file.
    assert list(cache_dir.glob("*.png"))


def test_child_failure_without_cache_renders_placeholder_not_raise(
    tmp_path: Path,
) -> None:
    regions = [
        {"plugin_id": "fake_a", "x": 0, "y": 0, "w": 100, "h": 60, "settings": {}}
    ]
    device_config = FakeDeviceConfig(tmp_path, _plugins_map("fake_a"))
    renderer = CompositeScreenRenderer(regions)
    FakeColorPlugin.fail_ids.add("fake_a")

    with _patch_get_plugin_instance():
        image = renderer.generate_image({}, device_config)

    assert image.size == (800, 480)


# ---------------------------------------------------------------------------
# Resizing a mismatched child image
# ---------------------------------------------------------------------------


def test_mismatched_child_image_size_gets_resized(tmp_path: Path) -> None:
    class WrongSizePlugin:
        def __init__(self, config: dict[str, str]) -> None:
            self.config = config

        def generate_image(
            self, settings: dict[str, Any], device_config: Any
        ) -> Image.Image:
            return Image.new("RGB", (10, 10), "purple")

    regions = [
        {"plugin_id": "fake_a", "x": 0, "y": 0, "w": 100, "h": 60, "settings": {}}
    ]
    device_config = FakeDeviceConfig(tmp_path, _plugins_map("fake_a"))
    renderer = CompositeScreenRenderer(regions)

    with patch(
        "refresh_task.composite_render.get_plugin_instance",
        side_effect=lambda config: WrongSizePlugin(config),
    ):
        image = renderer.generate_image({}, device_config)

    assert image.size == (800, 480)
    assert image.getpixel((50, 30)) == (128, 0, 128)


# ---------------------------------------------------------------------------
# Subprocess-boundary discipline (see _as_subprocess_would docstring)
# ---------------------------------------------------------------------------


def test_caching_survives_across_deep_copied_region_lists(tmp_path: Path) -> None:
    """Regions arrive as a fresh deep copy on every refresh in production.

    The cache must therefore live entirely on disk (keyed by content, not by
    object identity) — this pins that invariant.
    """
    base_regions = [
        {
            "plugin_id": "fake_a",
            "x": 0,
            "y": 0,
            "w": 100,
            "h": 60,
            "settings": {},
            "refresh_minutes": 15,
        }
    ]
    device_config = FakeDeviceConfig(tmp_path, _plugins_map("fake_a"))

    with _patch_get_plugin_instance():
        CompositeScreenRenderer(_as_subprocess_would(base_regions)).generate_image(
            {}, device_config
        )
        CompositeScreenRenderer(_as_subprocess_would(base_regions)).generate_image(
            {}, device_config
        )

    assert FakeColorPlugin.call_counts["fake_a"] == 1
