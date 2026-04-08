"""Tests for scripts/calibration_pattern.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from PIL import Image

# ---------------------------------------------------------------------------
# Loader (mirrors pattern used in test_diagnostic_snapshot.py)
# ---------------------------------------------------------------------------


def _load_script(script_name: str):
    """Load a scripts/ module by file path, avoiding sys.path pollution."""
    scripts_dir = Path(__file__).parent.parent / "scripts"
    spec = importlib.util.spec_from_file_location(
        script_name, scripts_dir / f"{script_name}.py"
    )
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


@pytest.fixture(scope="module")
def cp():
    """Return the calibration_pattern module."""
    return _load_script("calibration_pattern")


# ---------------------------------------------------------------------------
# Individual pattern generators — correct dimensions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "func_name",
    [
        "make_pure_colors",
        "make_grayscale_ramp",
        "make_dithering_grid",
        "make_font_resolution",
        "make_edge_sharpness",
        "make_full_refresh",
    ],
)
def test_pattern_returns_image_correct_size(cp, func_name):
    w, h = 400, 240
    func = getattr(cp, func_name)
    img = func(w, h)
    assert isinstance(img, Image.Image)
    assert img.size == (w, h)


@pytest.mark.parametrize(
    "func_name",
    [
        "make_pure_colors",
        "make_grayscale_ramp",
        "make_dithering_grid",
        "make_font_resolution",
        "make_edge_sharpness",
        "make_full_refresh",
    ],
)
def test_pattern_non_default_dimensions(cp, func_name):
    """Patterns work at non-default sizes."""
    w, h = 200, 120
    func = getattr(cp, func_name)
    img = func(w, h)
    assert img.size == (w, h)


# ---------------------------------------------------------------------------
# make_pure_colors specific checks
# ---------------------------------------------------------------------------


def test_pure_colors_mode(cp):
    img = cp.make_pure_colors(400, 240)
    assert img.mode == "RGB"


def test_pure_colors_has_red_corner(cp):
    """Top-left cell should contain red pixels."""
    img = cp.make_pure_colors(400, 240)
    # The first cell is Red — sample a pixel well inside the top-left block
    r, g, b = img.getpixel((5, 5))
    assert r == 255
    assert g == 0
    assert b == 0


# ---------------------------------------------------------------------------
# make_grayscale_ramp specific checks
# ---------------------------------------------------------------------------


def test_grayscale_ramp_extremes(cp):
    """Leftmost pixel should be near-black; rightmost should be near-white."""
    img = cp.make_grayscale_ramp(400, 240)
    left = img.getpixel((0, 120))
    right = img.getpixel((399, 120))
    assert left[0] < 20, f"leftmost pixel too bright: {left}"
    assert right[0] > 235, f"rightmost pixel too dim: {right}"


# ---------------------------------------------------------------------------
# make_full_refresh specific checks
# ---------------------------------------------------------------------------


def test_full_refresh_alternating_columns(cp):
    """Top half should alternate between black and white columns."""
    img = cp.make_full_refresh(400, 240)
    # column 0 → black, column 1 → white (or vice-versa), centre row of top half
    y = 60  # mid of top half
    px0 = img.getpixel((0, y))
    px1 = img.getpixel((1, y))
    assert px0 != px1, "Adjacent columns in top half should differ"


# ---------------------------------------------------------------------------
# main() — produces 6 PNG files for 'color' profile
# ---------------------------------------------------------------------------


def test_main_color_profile_produces_6_files(cp, tmp_path):
    import argparse

    args = argparse.Namespace(
        width=200,
        height=120,
        output_dir=str(tmp_path),
        profile="color",
    )
    written = cp.main(args)
    assert len(written) == 6
    for path in written:
        assert path.exists()
        assert path.suffix == ".png"


def test_main_grayscale_profile_produces_5_files(cp, tmp_path):
    import argparse

    args = argparse.Namespace(
        width=200,
        height=120,
        output_dir=str(tmp_path),
        profile="grayscale",
    )
    written = cp.main(args)
    assert len(written) == 5


def test_main_mono_profile_produces_2_files(cp, tmp_path):
    import argparse

    args = argparse.Namespace(
        width=200,
        height=120,
        output_dir=str(tmp_path),
        profile="mono",
    )
    written = cp.main(args)
    assert len(written) == 2


# ---------------------------------------------------------------------------
# mono profile — images are 1-bit
# ---------------------------------------------------------------------------


def test_mono_profile_images_are_1bit(cp, tmp_path):
    import argparse

    args = argparse.Namespace(
        width=200,
        height=120,
        output_dir=str(tmp_path),
        profile="mono",
    )
    written = cp.main(args)
    for path in written:
        with Image.open(path) as img:
            assert img.mode == "1", f"{path.name} is not 1-bit, got mode={img.mode!r}"


# ---------------------------------------------------------------------------
# Valid PNG check (PNG magic bytes)
# ---------------------------------------------------------------------------


def _is_valid_png(path: Path) -> bool:
    PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
    with open(path, "rb") as f:
        header = f.read(8)
    return header == PNG_MAGIC


def test_all_output_files_are_valid_pngs(cp, tmp_path):
    import argparse

    args = argparse.Namespace(
        width=200,
        height=120,
        output_dir=str(tmp_path),
        profile="color",
    )
    written = cp.main(args)
    for path in written:
        assert _is_valid_png(path), f"{path.name} does not have a valid PNG header"


# ---------------------------------------------------------------------------
# Output directory is created if it does not exist
# ---------------------------------------------------------------------------


def test_main_creates_output_dir(cp, tmp_path):
    import argparse

    new_dir = tmp_path / "nested" / "output"
    args = argparse.Namespace(
        width=200,
        height=120,
        output_dir=str(new_dir),
        profile="mono",
    )
    cp.main(args)
    assert new_dir.exists()


# ---------------------------------------------------------------------------
# ALL_PATTERNS has exactly 6 entries
# ---------------------------------------------------------------------------


def test_all_patterns_count(cp):
    assert len(cp.ALL_PATTERNS) == 6


# ---------------------------------------------------------------------------
# PROFILE_PATTERNS keys
# ---------------------------------------------------------------------------


def test_profile_keys(cp):
    assert set(cp.PROFILE_PATTERNS.keys()) == {"color", "grayscale", "mono"}


def test_color_profile_includes_all(cp):
    assert len(cp.PROFILE_PATTERNS["color"]) == 6
