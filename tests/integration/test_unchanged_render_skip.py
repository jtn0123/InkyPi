"""A render that matches the last refresh skips the panel only if the panel shows it.

The refresh loop skips the slow e-paper write when a render is unchanged. What
counts is what the panel shows now: after an error card, a history redisplay
or a display-settings change, the same render must be written again, or the
panel stays on the error card, the old picture or the old colours.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from display.display_manager import DisplayManager
from refresh_task import ManualRefresh, RefreshTask


class _Plugin:
    """Draws the same picture every time, or fails while ``failing`` is set."""

    config: dict[str, Any] = {"image_settings": []}

    def __init__(self) -> None:
        self.failing = False

    def generate_image(self, settings: Any, cfg: Any) -> Image.Image:
        if self.failing:
            raise RuntimeError("weather service down")
        return Image.new("RGB", cfg.get_resolution(), (40, 120, 200))


@pytest.fixture
def setup(
    device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[RefreshTask, DisplayManager, _Plugin, list[Image.Image]]]:
    plugin = _Plugin()
    monkeypatch.setattr(
        device_config_dev, "get_plugin", lambda pid: {"id": "dummy", "class": "D"}
    )
    monkeypatch.setattr(
        "refresh_task.plugin_lookup.get_plugin_instance", lambda cfg: plugin
    )
    dm = DisplayManager(device_config_dev)
    written: list[Image.Image] = []
    monkeypatch.setattr(
        dm.display,
        "display_image",
        lambda image, image_settings=None: written.append(image.copy()),
    )
    task = RefreshTask(device_config_dev, dm)
    task.start()
    try:
        yield task, dm, plugin, written
    finally:
        task.stop()


def _render(task: RefreshTask) -> None:
    """Run one manual refresh and wait until its panel write has finished."""
    task.manual_update(ManualRefresh("dummy", {}))
    # manual_update returns once the image is saved, before the panel write;
    # a display command queues behind the refresh, so it waits that out.
    task.run_display_command("barrier", lambda dm: None)


def _is_render(frame: Image.Image) -> bool:
    return frame.convert("RGB").getpixel((0, 0)) == (40, 120, 200)


def test_same_render_with_nothing_changed_skips_the_panel(setup: Any) -> None:
    task, _dm, _plugin, written = setup

    _render(task)
    _render(task)

    assert len(written) == 1
    assert task.device_config.get_refresh_info().used_cached is True


def test_same_render_after_an_error_card_replaces_the_card(setup: Any) -> None:
    task, _dm, plugin, written = setup

    _render(task)
    plugin.failing = True
    with pytest.raises(RuntimeError):
        _render(task)
    assert not _is_render(written[-1]), "the error card should be on the panel"

    plugin.failing = False
    _render(task)

    assert _is_render(written[-1]), "the panel was left on the error card"


def test_same_render_after_a_history_redisplay_is_written(
    setup: Any, tmp_path: Path
) -> None:
    task, _dm, _plugin, written = setup
    _render(task)

    old_frame = tmp_path / "display_20260101_000000.png"
    Image.new("RGB", task.device_config.get_resolution(), "white").save(old_frame)
    task.run_display_command(
        "history_redisplay", lambda dm: dm.display_preprocessed_image(str(old_frame))
    )
    assert not _is_render(written[-1])

    _render(task)

    assert _is_render(written[-1]), "the panel was left on the history image"


def test_same_render_after_a_display_settings_change_is_written(
    setup: Any,
) -> None:
    task, _dm, _plugin, written = setup
    _render(task)

    settings = dict(task.device_config.get_config("image_settings") or {})
    settings["saturation"] = 0.5
    task.device_config.update_value("image_settings", settings)
    _render(task)

    assert len(written) == 2, "the new saturation never reached the panel"
    assert task.device_config.get_refresh_info().used_cached is False
