"""Tests for GET /api/screenshot (JTN-450)."""

from __future__ import annotations

import os
from email.utils import formatdate

from PIL import Image

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_png(path: str) -> None:
    """Write a minimal 4x4 PNG to *path*."""
    img = Image.new("RGB", (4, 4), color=(10, 20, 30))
    img.save(path, format="PNG")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_screenshot_returns_200_with_png(client, device_config_dev):
    """GET /api/screenshot returns 200 with image/png when no WebP Accept."""
    _write_png(device_config_dev.processed_image_file)

    rv = client.get("/api/screenshot")

    assert rv.status_code == 200
    assert rv.content_type.startswith("image/")


def test_screenshot_returns_webp_when_accepted(client, device_config_dev):
    """GET /api/screenshot returns WebP when client sends Accept: image/webp."""
    _write_png(device_config_dev.processed_image_file)

    rv = client.get("/api/screenshot", headers={"Accept": "image/webp,*/*;q=0.8"})

    assert rv.status_code == 200
    assert rv.content_type == "image/webp"
    data = rv.data
    assert data[:4] == b"RIFF"
    assert data[8:12] == b"WEBP"


def test_screenshot_returns_png_when_webp_not_accepted(client, device_config_dev):
    """GET /api/screenshot returns PNG when Accept header does not include WebP."""
    _write_png(device_config_dev.processed_image_file)

    rv = client.get("/api/screenshot", headers={"Accept": "image/png,*/*"})

    assert rv.status_code == 200
    assert rv.content_type.startswith("image/png")


def test_screenshot_404_when_no_image(client, device_config_dev):
    """GET /api/screenshot returns 404 when neither image file exists."""
    # Ensure neither file exists (they shouldn't in a fresh tmp_path fixture).
    for p in (
        device_config_dev.processed_image_file,
        device_config_dev.current_image_file,
    ):
        if os.path.exists(p):
            os.remove(p)

    rv = client.get("/api/screenshot")

    assert rv.status_code == 404


def test_screenshot_falls_back_to_current_image(client, device_config_dev):
    """GET /api/screenshot uses current_image_file when processed is absent."""
    # Ensure processed image is absent, then write only the fallback file.
    processed = device_config_dev.processed_image_file
    if os.path.exists(processed):
        os.remove(processed)
    _write_png(device_config_dev.current_image_file)

    rv = client.get("/api/screenshot")

    assert rv.status_code == 200
    assert rv.content_type.startswith("image/")


def test_screenshot_last_modified_header_present(client, device_config_dev):
    """GET /api/screenshot includes a Last-Modified header."""
    _write_png(device_config_dev.processed_image_file)

    rv = client.get("/api/screenshot")

    assert rv.status_code == 200
    assert "Last-Modified" in rv.headers


def test_screenshot_cache_control_no_cache(client, device_config_dev):
    """GET /api/screenshot includes Cache-Control: no-cache, must-revalidate."""
    _write_png(device_config_dev.processed_image_file)

    rv = client.get("/api/screenshot")

    assert rv.status_code == 200
    cc = rv.headers.get("Cache-Control", "")
    assert "no-cache" in cc
    assert "must-revalidate" in cc


def test_screenshot_304_when_not_modified(client, device_config_dev):
    """GET /api/screenshot returns 304 when If-Modified-Since >= file mtime."""
    _write_png(device_config_dev.processed_image_file)

    # Fetch once to learn Last-Modified.
    rv1 = client.get("/api/screenshot")
    assert rv1.status_code == 200
    last_modified = rv1.headers["Last-Modified"]

    # Second request with the exact same timestamp should yield 304.
    rv2 = client.get("/api/screenshot", headers={"If-Modified-Since": last_modified})
    assert rv2.status_code == 304


def test_screenshot_200_when_modified_since_older(client, device_config_dev):
    """GET /api/screenshot returns 200 when If-Modified-Since is older than file."""
    _write_png(device_config_dev.processed_image_file)

    # Use a date far in the past.
    old_date = formatdate(0, usegmt=True)  # 1970-01-01 00:00:00 GMT

    rv = client.get("/api/screenshot", headers={"If-Modified-Since": old_date})
    assert rv.status_code == 200
