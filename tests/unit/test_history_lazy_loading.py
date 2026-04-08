# pyright: reportMissingImports=false
"""
Tests that /history images are lazy-loaded to prevent Playwright timeout (JTN-316).

Verifies that:
- Every <img> on /history has loading="lazy"
- Every <img> on /history has decoding="async"
- The page-level scripts use defer to avoid blocking HTML parsing
"""

import os
import re

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _html(client, path: str) -> str:
    resp = client.get(path)
    assert resp.status_code == 200, f"Expected 200 for {path}, got {resp.status_code}"
    return resp.get_data(as_text=True)


def _get_img_tags(html: str) -> list[str]:
    """Return all <img ...> tag strings from HTML."""
    return re.findall(r"<img\b[^>]*>", html, flags=re.IGNORECASE)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_history_page_all_imgs_have_loading_lazy(client, device_config_dev, tmp_path):
    """Every <img> rendered on /history must carry loading="lazy"."""
    # Create a few dummy history images so the grid renders
    history_dir = device_config_dev.history_image_dir
    for name in ("display_20240101_120000.png", "display_20240102_130000.png"):
        open(os.path.join(history_dir, name), "w").close()

    html = _html(client, "/history")
    imgs = _get_img_tags(html)
    assert imgs, "Expected at least one <img> tag on /history with dummy images"
    for tag in imgs:
        assert 'loading="lazy"' in tag, f'<img> tag missing loading="lazy": {tag}'


def test_history_page_all_imgs_have_decoding_async(client, device_config_dev, tmp_path):
    """Every <img> rendered on /history must carry decoding="async"."""
    history_dir = device_config_dev.history_image_dir
    for name in ("display_20240101_120000.png", "display_20240102_130000.png"):
        open(os.path.join(history_dir, name), "w").close()

    html = _html(client, "/history")
    imgs = _get_img_tags(html)
    assert imgs, "Expected at least one <img> tag on /history with dummy images"
    for tag in imgs:
        assert 'decoding="async"' in tag, f'<img> tag missing decoding="async": {tag}'


def test_history_page_scripts_use_defer(client):
    """lightbox.js and history_page.js must be loaded with defer to avoid blocking parse."""
    html = _html(client, "/history")

    # Find script tags that reference the history-specific scripts
    script_tags = re.findall(r"<script\b[^>]*>", html, flags=re.IGNORECASE)
    history_scripts = [
        t for t in script_tags if "lightbox.js" in t or "history_page.js" in t
    ]
    assert (
        history_scripts
    ), "Expected to find lightbox.js and history_page.js script tags"
    for tag in history_scripts:
        assert (
            "defer" in tag
        ), f"Script tag missing defer attribute (blocks HTML parse): {tag}"


def test_history_page_empty_state_no_imgs(client):
    """When history is empty the grid is not rendered and there are no .history-image tags."""
    html = _html(client, "/history")
    # history-image class should not appear when there are no images
    assert 'class="history-image"' not in html
