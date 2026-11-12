# pyright: reportMissingImports=false
"""Crisp rendering through the display layer: Inky hand-off, settings, pipeline.

The fake drivers below carry the module names and set_image() logic of the
real inky 2.6.0 drivers (``inky.inky_e673`` and ``inky.inky_uc8159``), so the
tests check what those drivers would do with the frame InkyPi hands them.
"""

from __future__ import annotations

import multiprocessing
import sys
import types
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image, ImageDraw

import refresh_task.plugin_lookup as plugin_lookup_mod
import refresh_task.task as task_mod
import refresh_task.worker as worker_mod
from display.crisp import CRISP_IMAGE_SETTING, SCREEN_RENDERING_KEY
from model import PluginInstance, RefreshInfo
from refresh_task import RefreshTask
from refresh_task.actions import PlaylistRefresh

E673_PURE = [
    [0, 0, 0],
    [255, 255, 255],
    [255, 255, 0],
    [255, 0, 0],
    [0, 0, 255],
    [0, 255, 0],
    [255, 255, 255],
]
E673_MEASURED = [
    [0, 0, 0],
    [161, 164, 165],
    [208, 190, 71],
    [156, 72, 75],
    [61, 59, 94],
    [58, 91, 70],
    [255, 255, 255],
]
UC8159_PURE = [
    [0, 0, 0],
    [255, 255, 255],
    [0, 255, 0],
    [0, 0, 255],
    [255, 0, 0],
    [255, 255, 0],
    [255, 140, 0],
    [255, 255, 255],
]
UC8159_MEASURED = [
    [57, 48, 57],
    [255, 255, 255],
    [58, 91, 70],
    [61, 59, 94],
    [156, 72, 75],
    [208, 190, 71],
    [177, 106, 73],
    [255, 255, 255],
]


class _FakeE673:
    """inky.inky_e673.Inky.set_image() from inky 2.6.0, minus the SPI."""

    BLACK = 0
    DESATURATED_PALETTE = E673_PURE
    SATURATED_PALETTE = E673_MEASURED

    def __init__(self, width: int = 800, height: int = 480) -> None:
        self.width, self.height = width, height
        self.images: list[Image.Image] = []
        self.dithered: list[bool] = []
        self.buf = np.zeros((height, width), dtype=np.uint8)
        self.shown = 0

    def set_border(self, _colour: int) -> None:
        pass

    def _palette_blend(self, saturation: float) -> list[int]:
        palette: list[int] = []
        for i in range(6):
            rs, gs, bs = [c * saturation for c in self.SATURATED_PALETTE[i]]
            rd, gd, bd = [c * (1.0 - saturation) for c in self.DESATURATED_PALETTE[i]]
            palette += [int(rs + rd), int(gs + gd), int(bs + bd)]
        return palette

    def set_image(self, image: Image.Image, saturation: float = 0.5) -> None:
        self.images.append(image)
        dither = Image.Dither.FLOYDSTEINBERG
        palette_image = Image.new("P", (1, 1))
        if image.mode == "P":
            palette = np.array(E673_PURE, dtype=np.uint8).flatten().tobytes()
            palette_image.putpalette(palette)
            if not image.palette.colors:
                image.putpalette(palette)
            if len(image.palette.colors) == 6:
                dither = Image.Dither.NONE
        else:
            palette_image.putpalette(self._palette_blend(saturation))
        self.dithered.append(dither != Image.Dither.NONE)
        image = image.convert("RGB").quantize(6, palette=palette_image, dither=dither)
        remap = np.array([0, 1, 2, 3, 5, 6])
        self.buf = remap[np.array(image, dtype=np.uint8)]

    def show(self) -> None:
        self.shown += 1


_FakeE673.__module__ = "inky.inky_e673"


class _FakeUC8159(_FakeE673):
    """inky.inky_uc8159.Inky.set_image(): mode-P pixels are raw colour codes."""

    DESATURATED_PALETTE = UC8159_PURE
    SATURATED_PALETTE = UC8159_MEASURED

    def set_image(self, image: Image.Image, saturation: float = 0.5) -> None:
        self.images.append(image)
        self.dithered.append(image.mode != "P")
        if image.mode != "P":
            pal = Image.new("P", (1, 1))
            pal.putpalette(
                [int(c) for row in UC8159_PURE[:7] for c in row] + [0, 0, 0] * 249
            )
            image = image.convert("RGB").quantize(
                8, palette=pal, dither=Image.Dither.FLOYDSTEINBERG
            )
        self.buf = np.array(image, dtype=np.uint8)


_FakeUC8159.__module__ = "inky.inky_uc8159"


class _FakeMonoWhat(_FakeE673):
    """A pHAT/wHAT-style driver: not in the verified list, keeps dithering."""


_FakeMonoWhat.__module__ = "inky.what"


def _install_fake_inky(monkeypatch: pytest.MonkeyPatch, driver: Any) -> None:
    inky_pkg = types.ModuleType("inky")
    inky_auto = types.ModuleType("inky.auto")
    inky_auto.auto = lambda: driver  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "inky", inky_pkg)
    monkeypatch.setitem(sys.modules, "inky.auto", inky_auto)


def _inky(monkeypatch: pytest.MonkeyPatch, device_config: Any, driver: Any) -> Any:
    _install_fake_inky(monkeypatch, driver)
    from display.inky_display import InkyDisplay

    return InkyDisplay(device_config)


def _ui_frame(size: tuple[int, int] = (800, 480)) -> Image.Image:
    img = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(img)
    draw.ellipse((100, 100, 180, 180), fill=(144, 202, 249))  # light-blue icon
    draw.rectangle((300, 100, 400, 110), fill=(0, 0, 0))
    draw.line((20, 300, 780, 300), fill=(170, 170, 170))
    return img


def _photo(size: tuple[int, int] = (800, 480)) -> Image.Image:
    rng = np.random.default_rng(1)
    return Image.fromarray(
        rng.integers(0, 256, size=(size[1], size[0], 3), dtype=np.uint8), "RGB"
    )


# --- InkyDisplay -------------------------------------------------------------


def test_crisp_frame_for_e673_is_pure_palette(
    monkeypatch: pytest.MonkeyPatch, device_config_dev: Any
) -> None:
    disp = _inky(monkeypatch, device_config_dev, _FakeE673())
    frame = disp.crisp_frame(_ui_frame())
    assert frame is not None
    colours = {c for _n, c in frame.getcolors(16)}
    assert colours <= {tuple(c) for c in E673_PURE}
    assert frame.getpixel((140, 140)) == (0, 0, 255)


def test_pure_palette_frame_reaches_e673_undithered(
    monkeypatch: pytest.MonkeyPatch, device_config_dev: Any
) -> None:
    driver = _FakeE673()
    disp = _inky(monkeypatch, device_config_dev, driver)
    frame = disp.crisp_frame(_ui_frame())
    disp.display_image(frame)

    sent = driver.images[-1]
    assert sent.mode == "P"
    assert len(sent.palette.colors) == 6
    assert driver.dithered == [False]
    # Native e673 codes: blue is 5 (the driver skips code 4), black 0, white 1.
    assert driver.buf[140, 140] == 5
    assert driver.buf[105, 350] == 0
    assert driver.buf[300, 400] == 0
    assert driver.buf[5, 5] == 1
    assert driver.shown == 1


def test_black_and_white_only_frame_is_still_undithered(
    monkeypatch: pytest.MonkeyPatch, device_config_dev: Any
) -> None:
    """A frame using two of the six colours keeps the six-entry palette."""
    driver = _FakeE673()
    disp = _inky(monkeypatch, device_config_dev, driver)
    img = Image.new("RGB", (800, 480), "white")
    ImageDraw.Draw(img).rectangle((10, 10, 50, 50), fill="black")
    disp.display_image(img)
    assert driver.dithered == [False]
    assert driver.buf[20, 20] == 0 and driver.buf[200, 200] == 1


def test_photo_frame_keeps_driver_dithering(
    monkeypatch: pytest.MonkeyPatch, device_config_dev: Any
) -> None:
    driver = _FakeE673()
    disp = _inky(monkeypatch, device_config_dev, driver)
    photo = _photo()
    disp.display_image(photo)
    assert driver.images[-1] is photo
    assert driver.dithered == [True]


def test_off_palette_colour_keeps_driver_dithering(
    monkeypatch: pytest.MonkeyPatch, device_config_dev: Any
) -> None:
    driver = _FakeE673()
    disp = _inky(monkeypatch, device_config_dev, driver)
    img = Image.new("RGB", (800, 480), "white")
    ImageDraw.Draw(img).rectangle((10, 10, 50, 50), fill=(250, 250, 250))
    disp.display_image(img)
    assert driver.dithered == [True]


def test_uc8159_gets_raw_colour_codes_including_orange(
    monkeypatch: pytest.MonkeyPatch, device_config_dev: Any
) -> None:
    driver = _FakeUC8159(600, 448)
    disp = _inky(monkeypatch, device_config_dev, driver)
    img = Image.new("RGB", (600, 448), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle((10, 10, 60, 60), fill=(255, 140, 0))  # orange
    draw.rectangle((100, 10, 150, 60), fill=(30, 60, 220))  # blue
    draw.rectangle((200, 10, 250, 60), fill=(20, 200, 40))  # green
    frame = disp.crisp_frame(img)
    assert frame is not None
    disp.display_image(frame)
    assert driver.dithered == [False]
    # uc8159 codes: BLACK 0, WHITE 1, GREEN 2, BLUE 3, RED 4, YELLOW 5, ORANGE 6.
    assert driver.buf[30, 30] == 6
    assert driver.buf[30, 120] == 3
    assert driver.buf[30, 220] == 2
    assert driver.buf[300, 300] == 1


def test_unverified_driver_has_no_crisp_path(
    monkeypatch: pytest.MonkeyPatch, device_config_dev: Any
) -> None:
    driver = _FakeMonoWhat()
    disp = _inky(monkeypatch, device_config_dev, driver)
    assert disp.crisp_frame(_ui_frame()) is None
    img = Image.new("RGB", (800, 480), "white")
    disp.display_image(img)
    assert driver.images[-1] is img
    assert driver.dithered == [True]


@pytest.mark.parametrize(
    "pure",
    [
        "not a palette",
        [
            [0, 0, 0],
            [255, 255, 255],
            [255, 255, 255],
            [255, 0, 0],
            [0, 0, 255],
            [0, 255, 0],
        ],
        [
            [1, 1, 1],
            [255, 255, 255],
            [255, 255, 0],
            [255, 0, 0],
            [0, 0, 255],
            [0, 255, 0],
        ],
    ],
)
def test_driver_with_unexpected_palette_is_left_alone(
    monkeypatch: pytest.MonkeyPatch, device_config_dev: Any, pure: Any
) -> None:
    driver = _FakeE673()
    driver.DESATURATED_PALETTE = pure  # type: ignore[assignment]
    disp = _inky(monkeypatch, device_config_dev, driver)
    assert disp.crisp_frame(_ui_frame()) is None


def test_driver_missing_palette_attribute_is_left_alone(
    monkeypatch: pytest.MonkeyPatch, device_config_dev: Any
) -> None:
    driver = _FakeE673()
    driver.SATURATED_PALETTE = None  # type: ignore[assignment]
    disp = _inky(monkeypatch, device_config_dev, driver)
    assert disp.crisp_frame(_ui_frame()) is None


def test_crisp_frame_dithers_photos_against_driver_blend(
    monkeypatch: pytest.MonkeyPatch, device_config_dev: Any
) -> None:
    device_config_dev.update_value("image_settings", {"inky_saturation": "bogus"})
    driver = _FakeE673()
    disp = _inky(monkeypatch, device_config_dev, driver)
    img = _ui_frame()
    img.paste(_photo((160, 96)), (560, 320))
    frame = disp.crisp_frame(img)
    assert frame is not None
    region = np.asarray(frame)[330:400, 570:710].reshape(-1, 3)
    assert len(np.unique(region, axis=0)) > 3


# --- DisplayManager ------------------------------------------------------------


def _manager(monkeypatch: pytest.MonkeyPatch, device_config: Any, driver: Any) -> Any:
    device_config.update_value("display_type", "inky")
    device_config.update_value("resolution", [driver.width, driver.height])
    device_config.update_value("orientation", "horizontal")
    _install_fake_inky(monkeypatch, driver)
    from display.display_manager import DisplayManager

    return DisplayManager(device_config)


def test_manager_crisps_flagged_frames_and_saves_crisp_preview(
    monkeypatch: pytest.MonkeyPatch, device_config_dev: Any
) -> None:
    driver = _FakeE673()
    dm = _manager(monkeypatch, device_config_dev, driver)
    dm.display_image(_ui_frame(), image_settings=[CRISP_IMAGE_SETTING])

    assert driver.dithered == [False]
    preview = Image.open(device_config_dev.processed_image_file)
    assert preview.getpixel((140, 140))[:3] == (0, 0, 255)
    # The raw render is kept as it was.
    current = Image.open(device_config_dev.current_image_file)
    assert current.getpixel((140, 140))[:3] == (144, 202, 249)


def test_manager_leaves_unflagged_frames_dithered(
    monkeypatch: pytest.MonkeyPatch, device_config_dev: Any
) -> None:
    driver = _FakeE673()
    dm = _manager(monkeypatch, device_config_dev, driver)
    dm.display_image(_ui_frame(), image_settings=[])
    assert driver.dithered == [True]


def test_always_dithered_setting_disables_crisp(
    monkeypatch: pytest.MonkeyPatch, device_config_dev: Any
) -> None:
    driver = _FakeE673()
    dm = _manager(monkeypatch, device_config_dev, driver)
    device_config_dev.update_value("image_settings", {SCREEN_RENDERING_KEY: "dithered"})
    dm.display_image(_ui_frame(), image_settings=[CRISP_IMAGE_SETTING])
    assert driver.dithered == [True]


def test_redisplay_of_saved_crisp_frame_stays_undithered(
    monkeypatch: pytest.MonkeyPatch, device_config_dev: Any
) -> None:
    """History redisplay and restore_last_frame have no plugin context."""
    driver = _FakeE673()
    dm = _manager(monkeypatch, device_config_dev, driver)
    dm.display_image(_ui_frame(), image_settings=[CRISP_IMAGE_SETTING])
    dm.restore_last_frame()
    dm.display_preprocessed_image(device_config_dev.processed_image_file)
    assert driver.dithered == [False, False, False]


def test_manager_with_mock_display_ignores_crisp_flag(
    device_config_dev: Any, tmp_path: Path
) -> None:
    device_config_dev.update_value("display_type", "mock")
    device_config_dev.update_value("resolution", [800, 480])
    device_config_dev.update_value("output_dir", str(tmp_path / "mock"))
    from display.display_manager import DisplayManager

    dm = DisplayManager(device_config_dev)
    dm.display_image(_ui_frame(), image_settings=[CRISP_IMAGE_SETTING])
    preview = Image.open(device_config_dev.processed_image_file)
    assert preview.getpixel((140, 140))[:3] == (144, 202, 249)


def test_manager_handles_odd_config_and_declining_display(
    monkeypatch: pytest.MonkeyPatch, device_config_dev: Any
) -> None:
    driver = _FakeE673()
    dm = _manager(monkeypatch, device_config_dev, driver)
    frame = _ui_frame()
    # Device image_settings that is not a mapping is treated as the default.
    monkeypatch.setattr(
        device_config_dev,
        "get_config",
        lambda key, default=None: (
            "garbage"
            if key == "image_settings"
            else type(device_config_dev).get_config(device_config_dev, key, default)
        ),
    )
    assert dm._maybe_crisp(frame, [CRISP_IMAGE_SETTING]) is not frame
    # A display that declines (returns None) leaves the frame alone.
    monkeypatch.setattr(dm.display, "crisp_frame", lambda _img: None)
    assert dm._maybe_crisp(frame, [CRISP_IMAGE_SETTING]) is frame


# --- Refresh pipeline, across the plugin subprocess ----------------------------

_PLUGIN_ID = "crisp_probe"


class _UiPlugin:
    def generate_image(self, settings: Any, device_config: Any) -> Any:
        return _ui_frame()

    def skip_display_condition(self, *_args: Any) -> None:
        return None


@pytest.mark.skipif(sys.platform == "win32", reason="fork start method is POSIX-only")
@pytest.mark.parametrize(
    ("image_settings", "expect_dithered"),
    [([CRISP_IMAGE_SETTING], False), ([], True)],
)
def test_refresh_through_subprocess_carries_crisp_flag(
    device_config_dev: Any,
    monkeypatch: pytest.MonkeyPatch,
    image_settings: list[str],
    expect_dithered: bool,
) -> None:
    """The plugin renders in a child process; the flag rides on plugin_config."""
    monkeypatch.setenv("INKYPI_PLUGIN_ISOLATION", "process")
    monkeypatch.setenv("INKYPI_PLUGIN_RETRY_MAX", "0")
    monkeypatch.setattr(
        task_mod, "_get_mp_context", lambda: multiprocessing.get_context("fork")
    )
    factory = lambda _cfg: _UiPlugin()  # noqa: E731
    monkeypatch.setattr(worker_mod, "get_plugin_instance", factory)
    monkeypatch.setattr(worker_mod, "load_plugins", lambda _plugins: None)
    monkeypatch.setattr(plugin_lookup_mod, "get_plugin_instance", factory)
    plugin_config = {
        "id": _PLUGIN_ID,
        "class": "Probe",
        "image_settings": image_settings,
    }
    monkeypatch.setattr(
        device_config_dev,
        "get_plugin",
        lambda pid: plugin_config if pid == _PLUGIN_ID else None,
    )
    instance = PluginInstance(
        plugin_id=_PLUGIN_ID, name="inst", settings={}, refresh={"interval": 60}
    )
    pm = device_config_dev.get_playlist_manager()
    if pm.get_playlist("Default") is None:
        pm.add_default_playlist()
    playlist = pm.get_playlist("Default")
    playlist.plugins.append(instance)

    driver = _FakeE673()
    dm = _manager(monkeypatch, device_config_dev, driver)
    task = RefreshTask(device_config_dev, dm)

    refresh_info, used_cached, _metrics = task._perform_refresh(
        PlaylistRefresh(playlist, instance, force=True),
        RefreshInfo(
            refresh_type="Manual Update",
            plugin_id="",
            refresh_time=None,
            image_hash=None,
        ),
        datetime(2026, 11, 12, 12, 0, tzinfo=UTC),
    )

    assert refresh_info is not None and not used_cached
    assert driver.dithered == [expect_dithered]
    if not expect_dithered:
        assert driver.buf[140, 140] == 5  # solid panel blue
