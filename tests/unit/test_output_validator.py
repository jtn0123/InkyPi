# pyright: reportMissingImports=false
"""Tests for utils.output_validator — dimension validation of plugin images."""

from typing import Any

import pytest
from PIL import Image
from pytest import MonkeyPatch

from utils.output_validator import OutputDimensionMismatch, validate_image_dimensions

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
# Integration: RefreshTask skips display push on dimension mismatch
# ---------------------------------------------------------------------------


def test_refresh_task_skips_display_on_dimension_mismatch(
    device_config_dev: Any, monkeypatch: MonkeyPatch
) -> None:
    """When a plugin returns an image with wrong dimensions the display should
    NOT be updated and plugin health should be marked as failure."""
    from display.display_manager import DisplayManager
    from refresh_task import ManualRefresh, RefreshTask

    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)

    expected_w, expected_h = device_config_dev.get_resolution()
    # Build a wrong-sized image (neither matching nor auto-rotatable).
    bad_image = Image.new("RGB", (expected_w + 10, expected_h + 10), "red")

    display_called: list[Image.Image] = []

    def _fake_execute_with_policy(
        refresh_action: Any,
        plugin_config: Any,
        current_dt: Any,
        request_id: Any = None,
    ) -> tuple[Image.Image, None]:
        return bad_image, None

    def _fake_display_image(image: Image.Image, **kwargs: Any) -> dict[str, Any]:
        display_called.append(image)
        return {}

    monkeypatch.setenv("INKYPI_PLUGIN_ISOLATION", "none")
    monkeypatch.setattr(task, "_execute_with_policy", _fake_execute_with_policy)
    monkeypatch.setattr(dm, "display_image", _fake_display_image)

    try:
        task.start()
        task.manual_update(ManualRefresh("ai_text", {}))
    except Exception:
        pass  # The mismatch causes _perform_refresh to return early — manual_update may raise
    finally:
        task.stop()

    assert display_called == [], "display_image must not be called for mismatched image"
    health = task.plugin_health.get("ai_text", {})
    assert (
        health.get("status") == "red"
    ), "plugin health should be red after dimension mismatch"
