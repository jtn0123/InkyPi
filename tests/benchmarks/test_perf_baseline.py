"""Performance baseline benchmarks for the InkyPi hot paths.

These benchmarks are deterministic, hermetic, and fast (each <1s). They run in CI
on every PR via the dedicated benchmark step (see .github/workflows/ci.yml).

Results are compared against a stored baseline (tests/benchmarks/baseline.json)
and fail CI when any benchmark regresses beyond the configured threshold
(default +15%). See docs/benchmarking.md for the full workflow.

Add a new benchmark only if it:
  * Has no network dependency
  * Has no wall-clock dependency
  * Runs in well under one second
  * Is representative of a real hot path
"""

from __future__ import annotations

import io
from typing import Any

from PIL import Image

# ---------------------------------------------------------------------------
# 1. PIL image resize + convert
# ---------------------------------------------------------------------------


def _make_test_image() -> Image.Image:
    """Build a small RGB image with deterministic content."""
    img = Image.new("RGB", (400, 240), (255, 255, 255))
    pixels = img.load()
    assert pixels is not None
    for x in range(400):
        for y in range(240):
            pixels[x, y] = ((x * 7) % 256, (y * 11) % 256, ((x + y) * 3) % 256)
    return img


def test_image_resize_and_convert(benchmark: Any) -> Any:
    """Resize a small image and convert to 1-bit — typical e-ink prep step."""
    src = _make_test_image()

    def resize_convert() -> Any:
        return src.resize((200, 120), Image.LANCZOS).convert("1")

    result = benchmark(resize_convert)
    assert result.size == (200, 120)
    assert result.mode == "1"


# ---------------------------------------------------------------------------
# 2. PIL image PNG encode
# ---------------------------------------------------------------------------


def test_image_png_encode(benchmark: Any) -> Any:
    """Encode a small image to PNG bytes — what /preview returns on every load."""
    src = _make_test_image()

    def encode() -> Any:
        buf = io.BytesIO()
        src.save(buf, format="PNG", optimize=False)
        return buf.getvalue()

    result = benchmark(encode)
    assert len(result) > 0
    assert result[:8] == b"\x89PNG\r\n\x1a\n"


# ---------------------------------------------------------------------------
# 3. Config read (JSON parse + validate)
# ---------------------------------------------------------------------------


def test_config_read(benchmark: Any, device_config_dev: Any) -> None:
    """Re-read the device config file from disk.

    The fixture builds a fresh on-disk device.json in tmp_path; we measure the
    `read_config()` path which is hit on every reload signal.
    """
    result = benchmark(device_config_dev.read_config)
    assert isinstance(result, dict)
    assert "name" in result


# ---------------------------------------------------------------------------
# 4. Plugin registry list scan
# ---------------------------------------------------------------------------


def test_plugin_registry_list_scan(benchmark: Any, device_config_dev: Any) -> None:
    """Walk src/plugins/ to read each plugin-info.json (startup hot path)."""
    result = benchmark(device_config_dev.read_plugins_list)
    assert isinstance(result, list)
    # The repo ships ~20+ plugins; just sanity check that we got several
    assert len(result) >= 5


# ---------------------------------------------------------------------------
# 5. Config read — cached (mtime unchanged)   JTN-519
# ---------------------------------------------------------------------------


def test_config_read_cached(benchmark: Any, device_config_dev: Any) -> None:
    """Measure read_config() when the file is unchanged (cache hit path).

    After the first read (which populates the mtime cache), subsequent calls
    should take only an os.stat() + dict copy — no JSON parse or schema
    validation.  This is the hot path hit on every RefreshTask tick.
    """
    # Warm the cache
    device_config_dev.read_config()

    result = benchmark(device_config_dev.read_config)
    assert isinstance(result, dict)
    assert "name" in result
