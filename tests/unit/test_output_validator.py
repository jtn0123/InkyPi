# pyright: reportMissingImports=false
"""Tests for utils.output_validator — dimension validation of plugin images."""

from typing import Any

import pytest
from PIL import Image
from pytest import MonkeyPatch

from utils.output_validator import (
    OutputDimensionMismatch,
    fit_image_to_device,
    fit_image_to_panel,
    oriented_resolution,
    validate_image_dimensions,
)

# ---------------------------------------------------------------------------
# Unit tests for validate_image_dimensions
# ---------------------------------------------------------------------------


def _img(w: int, h: int) -> Image.Image:
    return Image.new("RGB", (w, h), color="white")


class TestValidateImageDimensions:
    def test_matching_dims_returns_same_image(self) -> None:
        img = _img(800, 480)
        result = validate_image_dimensions(img, 800, 480, plugin_id="test_plugin")
        assert result is img

    def test_wrong_width_raises(self) -> None:
        img = _img(640, 480)
        with pytest.raises(OutputDimensionMismatch) as exc_info:
            validate_image_dimensions(img, 800, 480, plugin_id="bad_plugin")
        err = exc_info.value
        assert err.plugin_id == "bad_plugin"
        assert err.expected == (800, 480)
        assert err.actual == (640, 480)
        assert "bad_plugin" in str(err)
        assert "800x480" in str(err)
        assert "640x480" in str(err)

    def test_wrong_height_raises(self) -> None:
        img = _img(800, 600)
        with pytest.raises(OutputDimensionMismatch) as exc_info:
            validate_image_dimensions(img, 800, 480, plugin_id="tall_plugin")
        err = exc_info.value
        assert err.expected == (800, 480)
        assert err.actual == (800, 600)

    def test_both_dims_wrong_raises(self) -> None:
        img = _img(100, 100)
        with pytest.raises(OutputDimensionMismatch):
            validate_image_dimensions(img, 800, 480, plugin_id="tiny_plugin")

    def test_auto_rotate_transposed_dims(self) -> None:
        # Image is 480x800 but display expects 800x480 — should auto-rotate.
        img = _img(480, 800)
        result = validate_image_dimensions(img, 800, 480, plugin_id="rotated_plugin")
        assert result.size == (800, 480)

    def test_auto_rotate_disabled_raises_on_transposed(self) -> None:
        img = _img(480, 800)
        with pytest.raises(OutputDimensionMismatch):
            validate_image_dimensions(
                img, 800, 480, plugin_id="rotated_plugin", auto_rotate=False
            )

    def test_default_plugin_id_in_error_message(self) -> None:
        img = _img(100, 100)
        with pytest.raises(OutputDimensionMismatch) as exc_info:
            validate_image_dimensions(img, 800, 480)
        assert "<unknown>" in str(exc_info.value)


class TestOutputDimensionMismatch:
    def test_attributes(self) -> None:
        err = OutputDimensionMismatch("my_plugin", (800, 480), (640, 400))
        assert err.plugin_id == "my_plugin"
        assert err.expected == (800, 480)
        assert err.actual == (640, 400)

    def test_is_exception(self) -> None:
        err = OutputDimensionMismatch("p", (1, 2), (3, 4))
        assert isinstance(err, Exception)


# ---------------------------------------------------------------------------
# fit_image_to_panel: wrong-size images are fitted, not rejected
# ---------------------------------------------------------------------------

RED = (255, 0, 0)
BLUE = (0, 0, 255)
WHITE = (255, 255, 255)


def _marked(w: int, h: int) -> Image.Image:
    """A red image with a blue 10% block in each corner.

    If any corner block survives the fit, nothing at that edge was cropped.
    """
    img = Image.new("RGB", (w, h), RED)
    bw, bh = max(1, w // 10), max(1, h // 10)
    for x0, y0 in ((0, 0), (w - bw, 0), (0, h - bh), (w - bw, h - bh)):
        img.paste(BLUE, (x0, y0, x0 + bw, y0 + bh))
    return img


class _FakeDeviceConfig:
    def __init__(self, resolution: tuple[int, int], orientation: str) -> None:
        self._resolution = resolution
        self._orientation = orientation

    def get_resolution(self) -> tuple[int, int]:
        return self._resolution

    def get_config(self, key: str, default: Any = None) -> Any:
        return self._orientation if key == "orientation" else default


class TestFitImageToPanel:
    def test_matching_image_is_returned_untouched(self) -> None:
        img = _img(800, 480)
        assert fit_image_to_panel(img, 800, 480, plugin_id="p") is img

    def test_transposed_image_is_rotated_not_padded(self) -> None:
        result = fit_image_to_panel(_marked(480, 800), 800, 480, plugin_id="p")
        assert result.size == (800, 480)
        # Rotation keeps the full frame: corners are still the blue markers.
        assert result.getpixel((2, 2)) == BLUE

    @pytest.mark.parametrize("size", [(1600, 960), (700, 420), (805, 480)])
    def test_same_ratio_is_resized_to_fill(
        self, size: tuple[int, int], caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level("WARNING", logger="utils.output_validator")
        result = fit_image_to_panel(_marked(*size), 800, 480, plugin_id="newspaper")

        assert result.size == (800, 480)
        # Plain resize: every corner marker is still in its corner.
        for xy in ((3, 3), (796, 3), (3, 476), (796, 476)):
            assert result.getpixel(xy) == BLUE
        assert "newspaper" in caplog.text
        assert f"{size[0]}x{size[1]}" in caplog.text
        assert "800x480" in caplog.text
        assert "resized" in caplog.text

    def test_different_ratio_is_padded_without_cropping(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level("WARNING", logger="utils.output_validator")
        # The real WPOTD original that used to be rejected (portrait).
        result = fit_image_to_panel(_marked(2201, 2935), 800, 480, plugin_id="wpotd")

        assert result.size == (800, 480)
        # Scaled to 360x480 and centred: 220px white bars either side.
        assert result.getpixel((5, 240)) == WHITE
        assert result.getpixel((794, 240)) == WHITE
        assert result.getpixel((400, 240)) == RED
        # All four corner markers survive — nothing was cropped.
        for xy in ((224, 3), (575, 3), (224, 476), (575, 476)):
            assert result.getpixel(xy) == BLUE
        assert "wpotd" in caplog.text
        assert "2201x2935" in caplog.text
        assert "padded" in caplog.text

    def test_wide_image_is_letterboxed_top_and_bottom(self) -> None:
        result = fit_image_to_panel(_marked(1000, 300), 800, 480, plugin_id="p")
        assert result.size == (800, 480)
        assert result.getpixel((400, 2)) == WHITE
        assert result.getpixel((400, 477)) == WHITE
        assert result.getpixel((3, 240 - 120 + 3)) == BLUE

    @pytest.mark.parametrize("mode", ["RGBA", "P", "LA"])
    def test_other_modes_are_padded_as_rgb(self, mode: str) -> None:
        img = Image.new("RGB", (300, 300), RED).convert(mode)
        result = fit_image_to_panel(img, 800, 480, plugin_id="p")
        assert result.size == (800, 480)
        assert result.mode == "RGB"
        assert result.getpixel((2, 240)) == WHITE

    def test_grayscale_is_padded_in_its_own_mode(self) -> None:
        img = Image.new("L", (300, 300), 0)
        result = fit_image_to_panel(img, 800, 480, plugin_id="p")
        assert result.mode == "L"
        assert result.getpixel((2, 240)) == 255
        assert result.getpixel((400, 240)) == 0

    def test_empty_image_still_raises(self) -> None:
        with pytest.raises(OutputDimensionMismatch):
            fit_image_to_panel(Image.new("RGB", (0, 0)), 800, 480, plugin_id="p")

    def test_empty_target_raises(self) -> None:
        with pytest.raises(OutputDimensionMismatch):
            fit_image_to_panel(_img(10, 10), 0, 480, plugin_id="p")

    def test_source_over_the_pixel_limit_is_refused(
        self, monkeypatch: MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level("ERROR", logger="utils.output_validator")
        monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)
        with pytest.raises(OutputDimensionMismatch):
            fit_image_to_panel(_img(100, 100), 800, 480, plugin_id="huge")
        assert "huge" in caplog.text
        assert "refusing" in caplog.text

    def test_pixel_limit_falls_back_when_pillow_guard_is_disabled(
        self, monkeypatch: MonkeyPatch
    ) -> None:
        monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", None)
        result = fit_image_to_panel(_img(100, 100), 800, 480, plugin_id="p")
        assert result.size == (800, 480)


class TestOrientedResolution:
    def test_horizontal_keeps_resolution(self) -> None:
        cfg = _FakeDeviceConfig((800, 480), "horizontal")
        assert oriented_resolution(cfg) == (800, 480)

    def test_vertical_swaps_to_portrait(self) -> None:
        cfg = _FakeDeviceConfig((800, 480), "vertical")
        assert oriented_resolution(cfg) == (480, 800)

    def test_fit_image_to_device_uses_the_oriented_canvas(self) -> None:
        cfg = _FakeDeviceConfig((800, 480), "vertical")
        result = fit_image_to_device(_marked(700, 420), cfg, "newspaper")
        assert result.size == (480, 800)
        # A correct portrait frame passes through untouched in vertical mode.
        portrait = _img(480, 800)
        assert fit_image_to_device(portrait, cfg, "clock") is portrait


# ---------------------------------------------------------------------------
# Integration: RefreshTask fits a wrong-size image and records it healthy
# ---------------------------------------------------------------------------


def _run_manual_refresh(
    device_config_dev: Any, monkeypatch: MonkeyPatch, image: Image.Image
) -> tuple[Any, list[Image.Image], Any]:
    from datetime import UTC, datetime

    from display.display_manager import DisplayManager
    from refresh_task import ManualRefresh, RefreshTask

    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)
    displayed: list[Image.Image] = []

    def _fake_execute_with_policy(
        refresh_action: Any,
        plugin_config: Any,
        current_dt: Any,
        request_id: Any = None,
    ) -> tuple[Image.Image, None]:
        return image, None

    def _fake_display_image(image: Image.Image, **kwargs: Any) -> dict[str, Any]:
        displayed.append(image)
        return {}

    monkeypatch.setattr(task, "_execute_with_policy", _fake_execute_with_policy)
    monkeypatch.setattr(dm, "display_image", _fake_display_image)
    result = task._perform_refresh(
        ManualRefresh("ai_text", {}),
        device_config_dev.get_refresh_info(),
        datetime.now(UTC),
    )
    return task, displayed, result


@pytest.mark.parametrize(
    ("size", "how"),
    [((1024, 614), "resized"), ((1024, 676), "padded"), ((700, 420), "resized")],
)
def test_refresh_task_fits_wrong_size_image_and_stays_healthy(
    size: tuple[int, int],
    how: str,
    device_config_dev: Any,
    monkeypatch: MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A wrong-size image is fitted and displayed; the refresh is healthy.

    1024x676 is the APOD frame that paused the owner's plugin for months.
    """
    caplog.set_level("WARNING", logger="utils.output_validator")
    task, displayed, (refresh_info, _cached, _metrics) = _run_manual_refresh(
        device_config_dev, monkeypatch, _marked(*size)
    )

    assert len(displayed) == 1
    shown = displayed[0]
    assert shown.size == device_config_dev.get_resolution() == (800, 480)
    # Content not cropped: the source's top-left corner marker is shown. When
    # padded (a taller source), the picture spans the full height and is
    # centred horizontally.
    left = 0 if how == "resized" else (800 - round(size[0] * 480 / size[1])) // 2
    assert shown.getpixel((left + 3, 3)) == BLUE
    if how == "padded":
        assert shown.getpixel((2, 240)) == WHITE
    assert refresh_info is not None
    health = task.plugin_health["ai_text"]
    assert health["status"] == "green"
    assert health["failure_count"] == 0
    assert f"{size[0]}x{size[1]}" in caplog.text
    assert how in caplog.text


def test_refresh_task_skips_display_when_image_cannot_be_fitted(
    device_config_dev: Any, monkeypatch: MonkeyPatch
) -> None:
    """An image that cannot be fitted still fails the refresh and keeps the
    current display, exactly like the old dimension-mismatch path."""
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)
    task, displayed, result = _run_manual_refresh(
        device_config_dev, monkeypatch, _img(810, 490)
    )

    assert displayed == [], "display_image must not be called for an unfittable image"
    assert result == (None, False, {})
    health = task.plugin_health.get("ai_text", {})
    assert health.get("status") == "red"
    assert "wrong dimensions" in str(health.get("last_error"))
