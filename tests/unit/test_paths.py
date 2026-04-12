# pyright: reportMissingImports=false
"""Tests for the utils.paths module."""

import os


def test_base_dir_points_to_src():
    from utils.paths import BASE_DIR

    assert os.path.isdir(BASE_DIR)
    assert os.path.basename(BASE_DIR) == "src"


def test_default_constants_exist():
    from utils.paths import (
        CURRENT_IMAGE_FILE,
        DEFAULT_PREVIEW_IMAGE,
        HISTORY_IMAGE_DIR,
        PLUGIN_IMAGE_DIR,
        PROCESSED_IMAGE_FILE,
    )

    # They should all be absolute paths under src/
    for p in [
        CURRENT_IMAGE_FILE,
        PROCESSED_IMAGE_FILE,
        PLUGIN_IMAGE_DIR,
        HISTORY_IMAGE_DIR,
        DEFAULT_PREVIEW_IMAGE,
    ]:
        assert os.path.isabs(p)
        assert "static" in p or "images" in p


def test_resolve_runtime_paths_no_override():
    from utils.paths import (
        CURRENT_IMAGE_FILE,
        HISTORY_IMAGE_DIR,
        PLUGIN_IMAGE_DIR,
        PROCESSED_IMAGE_FILE,
        resolve_runtime_paths,
    )

    result = resolve_runtime_paths(None)
    assert result["current_image_file"] == CURRENT_IMAGE_FILE
    assert result["processed_image_file"] == PROCESSED_IMAGE_FILE
    assert result["plugin_image_dir"] == PLUGIN_IMAGE_DIR
    assert result["history_image_dir"] == HISTORY_IMAGE_DIR


def test_resolve_runtime_paths_empty_string():
    from utils.paths import CURRENT_IMAGE_FILE, resolve_runtime_paths

    result = resolve_runtime_paths("")
    assert result["current_image_file"] == CURRENT_IMAGE_FILE


def test_resolve_runtime_paths_with_override(tmp_path):
    from utils.paths import resolve_runtime_paths

    result = resolve_runtime_paths(str(tmp_path))
    images_dir = os.path.join(str(tmp_path), "images")
    assert result["current_image_file"] == os.path.join(images_dir, "current_image.png")
    assert result["processed_image_file"] == os.path.join(
        images_dir, "processed_image.png"
    )
    assert result["plugin_image_dir"] == os.path.join(images_dir, "plugins")
    assert result["history_image_dir"] == os.path.join(images_dir, "history")
