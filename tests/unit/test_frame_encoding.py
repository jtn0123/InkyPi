"""One lossless encode per processed frame, and RGB back out for the panel."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from display.display_manager import DisplayManager, encode_frame_png, panel_copy

SIX = [(0, 0, 0), (255, 255, 255), (255, 255, 0), (255, 0, 0), (0, 0, 255), (0, 255, 0)]


def _from_palette(palette: list[tuple[int, int, int]], seed: int = 0) -> Image.Image:
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, len(palette), size=(48, 80))
    return Image.fromarray(np.asarray(palette, dtype=np.uint8)[indices], "RGB")


def _decode(data: bytes) -> Image.Image:
    with Image.open(io.BytesIO(data)) as img:
        img.load()
        return img.copy()


@pytest.mark.parametrize(
    ("image", "stored_mode"),
    [
        (_from_palette(SIX), "P"),
        # Colours a level apart: still exact, through the slower lookup.
        (_from_palette([(100, 100, 100), (101, 101, 101), (102, 102, 102)]), "P"),
        (
            Image.fromarray(
                np.random.default_rng(1).integers(0, 256, (48, 80, 3), dtype=np.uint8),
                "RGB",
            ),
            "RGB",
        ),
        (Image.new("RGBA", (40, 30), (10, 20, 30, 128)), "RGBA"),
        (Image.new("L", (40, 30), 77), "L"),
    ],
    ids=["six-colours", "near-greys", "photo", "rgba", "grey"],
)
def test_encoded_frame_is_lossless(image: Image.Image, stored_mode: str) -> None:
    stored = _decode(encode_frame_png(image))
    assert stored.mode == stored_mode
    assert stored.convert(image.mode).tobytes() == image.tobytes()


def test_palette_frame_is_smaller_than_rgb() -> None:
    frame = _from_palette(SIX).resize((800, 480), Image.Resampling.NEAREST)
    rgb = io.BytesIO()
    frame.save(rgb, format="PNG", compress_level=6)
    assert len(encode_frame_png(frame)) < len(rgb.getvalue())


def test_panel_copy_hands_drivers_rgb() -> None:
    palette_frame = _decode(encode_frame_png(_from_palette(SIX)))
    assert palette_frame.mode == "P"
    copy = panel_copy(palette_frame)
    assert copy.mode == "RGB"
    assert copy.tobytes() == _from_palette(SIX).tobytes()

    rgb = Image.new("RGB", (4, 4), "red")
    other = panel_copy(rgb)
    assert other is not rgb and other.tobytes() == rgb.tobytes()


class _Recorder:
    def __init__(self) -> None:
        self.images: list[Image.Image] = []

    def display_image(
        self, image: Image.Image, image_settings: list[object] | None = None
    ) -> None:
        self.images.append(image)


def _manager(device_config: Any) -> tuple[DisplayManager, _Recorder]:
    device_config.update_value("display_type", "mock")
    dm = DisplayManager(device_config)
    recorder = _Recorder()
    dm.display = recorder
    return dm, recorder


def test_restore_last_frame_sends_rgb_from_a_palette_preview(
    device_config_dev: Any,
) -> None:
    dm, recorder = _manager(device_config_dev)
    frame = _from_palette(SIX)
    Path(device_config_dev.processed_image_file).write_bytes(encode_frame_png(frame))

    assert dm.restore_last_frame() is not None

    sent = recorder.images[-1]
    assert sent.mode == "RGB"
    assert sent.tobytes() == frame.tobytes()


def test_history_redisplay_copies_the_file_and_sends_rgb(
    device_config_dev: Any, tmp_path: Path
) -> None:
    dm, recorder = _manager(device_config_dev)
    frame = _from_palette(SIX, seed=2)
    snapshot = tmp_path / "display_20260101_000000.png"
    snapshot.write_bytes(encode_frame_png(frame))

    dm.display_preprocessed_image(str(snapshot))

    sent = recorder.images[-1]
    assert sent.mode == "RGB"
    assert sent.tobytes() == frame.tobytes()
    # The previews are byte copies of the snapshot, not re-encodes.
    for preview in (
        device_config_dev.current_image_file,
        device_config_dev.processed_image_file,
    ):
        assert Path(preview).read_bytes() == snapshot.read_bytes()
