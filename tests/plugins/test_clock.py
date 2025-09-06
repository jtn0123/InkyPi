# pyright: reportMissingImports=false
import math
import types
from datetime import datetime

import pytest
from PIL import Image


def _fixed_dt(h=3, m=15, s=0):
    return datetime(2024, 1, 1, h, m, s)


def test_static_format_time():
    from plugins.clock.clock import Clock

    assert Clock.format_time(9, 5, zero_pad=False) == "9:5"
    assert Clock.format_time(9, 5, zero_pad=True) == "09:05"
    assert Clock.format_time(12, 0, zero_pad=True) == "12:00"


def test_static_pad_color():
    from plugins.clock.clock import Clock

    assert Clock.pad_color((1, 2, 3)) == (1, 2, 3, 255)
    assert Clock.pad_color((10, 20, 30, 40)) == (10, 20, 30, 40)


def test_static_calculate_rectangle_corners():
    from plugins.clock.clock import Clock

    start = (0.0, 0.0)
    end = (10.0, 0.0)
    corners = Clock.calculate_rectangle_corners(start, end, 2)
    # Expect vertical offsets at start and end
    xs = {round(c[0], 4) for c in corners}
    ys = {round(c[1], 4) for c in corners}
    assert min(xs) >= -1e-6
    assert max(xs) <= 10 + 1e-6
    assert ys == {-2.0, 2.0}


def test_static_calculate_clock_angles():
    from plugins.clock.clock import Clock

    dt = _fixed_dt(3, 0, 0)
    hour_angle, minute_angle = Clock.calculate_clock_angles(dt)
    # 3:00 -> hour hand at 3 o'clock, minute at 12 o'clock
    # In degrees: hour = 0 deg (to the right) translates to 0°, but implementation defines 12 o'clock as 90° CW
    # We assert relative positioning: minute at 12 (pi/2 rad), hour at 0 (0 rad)
    assert math.isclose(minute_angle, math.radians(90.0), rel_tol=0, abs_tol=1e-6)
    # Hour at 3 o'clock -> 0 degrees after modulo mapping -> radians near 0
    assert math.isclose(hour_angle % (2 * math.pi), 0.0, rel_tol=0, abs_tol=1e-6)


def test_static_translate_word_grid_positions_edges():
    from plugins.clock.clock import Clock

    # Edge near o'clock
    letters_00 = Clock.translate_word_grid_positions(3, 0)
    assert [9, 5] in letters_00  # 'O'
    letters_59 = Clock.translate_word_grid_positions(3, 59)
    assert [9, 5] in letters_59


def test_draw_gradient_image_mode_and_size():
    from plugins.clock.clock import Clock

    img = Clock.draw_gradient_image(120, 80, 0.0, math.pi, (0, 0, 0, 0), (255, 0, 0, 255))
    assert isinstance(img, Image.Image)
    assert img.mode == "RGBA"
    assert img.size == (120, 80)


def test_draw_hour_marks_image_unchanged_size_and_mode():
    from plugins.clock.clock import Clock

    base = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    out = Clock.draw_hour_marks(base, radius=80)
    assert out.size == (200, 200)
    assert out.mode == "RGBA"


def test_draw_clock_hand_image_unchanged_size_and_mode():
    from plugins.clock.clock import Clock

    base = Image.new("RGBA", (300, 200), (0, 0, 0, 0))
    out = Clock.draw_clock_hand(base, length=60, angle=math.radians(0), hand_color=(255, 0, 0), border_color=(255, 255, 255))
    assert out.size == (300, 200)
    assert out.mode == "RGBA"


def test_generate_image_face_selection_and_orientation(device_config_dev, monkeypatch):
    from plugins.clock.clock import Clock

    # Horizontal
    cfg = device_config_dev
    cfg.update_value("timezone", "UTC", write=False)
    cfg.update_value("orientation", "horizontal", write=False)

    clock = Clock({"id": "clock"})
    img = clock.generate_image({"selectedClockFace": "Digital Clock", "primaryColor": "#ffffff", "secondaryColor": "#000000"}, cfg)
    assert isinstance(img, Image.Image)
    assert img.size == tuple(cfg.get_resolution())

    # Vertical orientation should flip width/height
    cfg.update_value("orientation", "vertical", write=False)
    img_v = clock.generate_image({"selectedClockFace": "Digital Clock", "primaryColor": "#ffffff", "secondaryColor": "#000000"}, cfg)
    w, h = cfg.get_resolution()
    assert img_v.size == (h, w)


def test_generate_image_default_face_when_invalid(device_config_dev):
    from plugins.clock.clock import Clock, DEFAULT_CLOCK_FACE

    cfg = device_config_dev
    cfg.update_value("timezone", "UTC", write=False)

    clock = Clock({"id": "clock"})
    img = clock.generate_image({"selectedClockFace": "Not A Face", "primaryColor": "#ffffff", "secondaryColor": "#000000"}, cfg)
    assert isinstance(img, Image.Image)
    assert img.size[0] > 0


def test_generate_image_error_path(device_config_dev, monkeypatch):
    from plugins.clock.clock import Clock

    # Force a failure inside one of the draw methods (e.g., digital)
    class Boom(Exception):
        pass

    def boom(*args, **kwargs):
        raise Boom("boom")

    import plugins.clock.clock as clock_mod
    monkeypatch.setattr(clock_mod.Clock, "draw_digital_clock", boom, raising=True)

    cfg = device_config_dev
    cfg.update_value("timezone", "UTC", write=False)

    clock = Clock({"id": "clock"})
    with pytest.raises(RuntimeError):
        clock.generate_image({"selectedClockFace": "Digital Clock", "primaryColor": "#ffffff", "secondaryColor": "#000000"}, cfg)


