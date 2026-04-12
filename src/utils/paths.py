"""Centralized path resolution for InkyPi.

All image/config directory paths are resolved here so that every module
imports from one place instead of reaching into ``Config`` class attributes.
"""

import os

# Base path: the ``src/`` directory that contains this package.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Default image paths (relative to BASE_DIR).
_IMAGES_DIR = os.path.join(BASE_DIR, "static", "images")

CURRENT_IMAGE_FILE = os.path.join(_IMAGES_DIR, "current_image.png")
PROCESSED_IMAGE_FILE = os.path.join(_IMAGES_DIR, "processed_image.png")
PLUGIN_IMAGE_DIR = os.path.join(_IMAGES_DIR, "plugins")
HISTORY_IMAGE_DIR = os.path.join(_IMAGES_DIR, "history")
DEFAULT_PREVIEW_IMAGE = os.path.join(_IMAGES_DIR, "inkypi.png")


def resolve_runtime_paths(
    runtime_dir: str | None = None,
) -> dict[str, str]:
    """Return a dict of image path overrides based on an optional runtime dir.

    When *runtime_dir* is falsy the defaults (class-level constants above) are
    returned.  When it is set, all image paths are rooted under
    ``<runtime_dir>/images/``.

    Keys: ``current_image_file``, ``processed_image_file``,
    ``plugin_image_dir``, ``history_image_dir``.
    """
    if not runtime_dir:
        return {
            "current_image_file": CURRENT_IMAGE_FILE,
            "processed_image_file": PROCESSED_IMAGE_FILE,
            "plugin_image_dir": PLUGIN_IMAGE_DIR,
            "history_image_dir": HISTORY_IMAGE_DIR,
        }

    runtime_images_dir = os.path.join(runtime_dir, "images")
    return {
        "current_image_file": os.path.join(runtime_images_dir, "current_image.png"),
        "processed_image_file": os.path.join(runtime_images_dir, "processed_image.png"),
        "plugin_image_dir": os.path.join(runtime_images_dir, "plugins"),
        "history_image_dir": os.path.join(runtime_images_dir, "history"),
    }
