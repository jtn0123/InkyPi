"""Performance baseline benchmarks for the InkyPi hot paths.

These benchmarks are deterministic, hermetic, and fast (each <1s). They run in CI
on every PR via the dedicated benchmark step (see .github/workflows/ci.yml).

For now this just *records* the numbers — auto-comparison against a stored
baseline (and a regression gate) will be added in a follow-up. See JTN-293.

Add a new benchmark only if it:
  * Has no network dependency
  * Has no wall-clock dependency
  * Runs in well under one second
  * Is representative of a real hot path
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

# ---------------------------------------------------------------------------
# 1. HTTP cache hit lookup
# ---------------------------------------------------------------------------


@pytest.fixture()
def warm_http_cache():
    """A pre-warmed HTTPCache containing one entry the benchmark can hit."""
    from utils.http_cache import HTTPCache

    cache = HTTPCache(default_ttl=3600.0, max_size=128, max_entries=128)

    # Build a fake response we can stuff into the cache directly.
    import requests

    response = requests.Response()
    response.status_code = 200
    response._content = b'{"hello": "world"}'
    response.headers["Content-Type"] = "application/json"

    cache.put("https://example.com/api", response)
    return cache


def test_http_cache_hit_lookup(benchmark, warm_http_cache):
    """Measure the cost of a single cache hit (the hot path for cached plugins)."""
    result = benchmark(warm_http_cache.get, "https://example.com/api")
    assert result is not None
    assert result.status_code == 200


# ---------------------------------------------------------------------------
# 2. PIL image resize + convert
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


def test_image_resize_and_convert(benchmark):
    """Resize a small image and convert to 1-bit — typical e-ink prep step."""
    src = _make_test_image()

    def resize_convert():
        return src.resize((200, 120), Image.LANCZOS).convert("1")

    result = benchmark(resize_convert)
    assert result.size == (200, 120)
    assert result.mode == "1"


# ---------------------------------------------------------------------------
# 3. PIL image PNG encode
# ---------------------------------------------------------------------------


def test_image_png_encode(benchmark):
    """Encode a small image to PNG bytes — what /preview returns on every load."""
    src = _make_test_image()

    def encode():
        buf = io.BytesIO()
        src.save(buf, format="PNG", optimize=False)
        return buf.getvalue()

    result = benchmark(encode)
    assert len(result) > 0
    assert result[:8] == b"\x89PNG\r\n\x1a\n"


# ---------------------------------------------------------------------------
# 4. Config read (JSON parse + validate)
# ---------------------------------------------------------------------------


def test_config_read(benchmark, device_config_dev):
    """Re-read the device config file from disk.

    The fixture builds a fresh on-disk device.json in tmp_path; we measure the
    `read_config()` path which is hit on every reload signal.
    """
    result = benchmark(device_config_dev.read_config)
    assert isinstance(result, dict)
    assert "name" in result


# ---------------------------------------------------------------------------
# 5. Plugin registry list scan
# ---------------------------------------------------------------------------


def test_plugin_registry_list_scan(benchmark, device_config_dev):
    """Walk src/plugins/ to read each plugin-info.json (startup hot path)."""
    result = benchmark(device_config_dev.read_plugins_list)
    assert isinstance(result, list)
    # The repo ships ~20+ plugins; just sanity check that we got several
    assert len(result) >= 5
