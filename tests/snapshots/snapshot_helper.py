"""Snapshot helper for plugin image golden-file tests.

Usage pattern
-------------
from tests.snapshots.snapshot_helper import assert_image_snapshot

# In a test (with datetime frozen / network mocked):
result = plugin.generate_image(settings, device_config)
assert_image_snapshot(result, "year_progress", "mid_year")

Updating baselines
------------------
Run ``python scripts/update_snapshots.py`` — or pass ``--snapshot-update``
to pytest (which sets the SNAPSHOT_UPDATE env-var that this helper honours).

Storage layout
--------------
tests/snapshots/<plugin_name>/<case_name>.png   — the canonical PNG
tests/snapshots/<plugin_name>/<case_name>.sha256 — SHA-256 hex digest

The digest file is what the test compares; the PNG is kept for human review.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from PIL import Image

_SNAPSHOTS_ROOT = Path(__file__).parent

UPDATE_MODE = os.getenv("SNAPSHOT_UPDATE", "").strip().lower() in ("1", "true", "yes")


def _snapshot_paths(plugin_name: str, case_name: str) -> tuple[Path, Path]:
    """Return (png_path, digest_path) for the given plugin/case."""
    base = _SNAPSHOTS_ROOT / plugin_name / case_name
    return base.with_suffix(".png"), base.with_suffix(".sha256")


def _image_sha256(image: Image.Image) -> str:
    """Return the SHA-256 hex digest of the raw PNG bytes of *image*."""
    import io

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return hashlib.sha256(buf.getvalue()).hexdigest()


def save_snapshot(image: Image.Image, plugin_name: str, case_name: str) -> None:
    """Write / overwrite the PNG and digest files for the given case."""
    png_path, digest_path = _snapshot_paths(plugin_name, case_name)
    png_path.parent.mkdir(parents=True, exist_ok=True)

    import io

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    png_path.write_bytes(png_bytes)
    digest_path.write_text(hashlib.sha256(png_bytes).hexdigest() + "\n")


def assert_image_snapshot(
    image: Image.Image,
    plugin_name: str,
    case_name: str,
) -> None:
    """Assert that *image* matches the stored baseline snapshot.

    If SNAPSHOT_UPDATE is set the baseline is written/overwritten instead of
    compared, so the test always passes on an update run.

    Raises
    ------
    FileNotFoundError
        When no baseline exists yet.  Run ``python scripts/update_snapshots.py``
        (or ``SNAPSHOT_UPDATE=1 pytest``) to create it.
    AssertionError
        When the image hash doesn't match the stored baseline.
    """
    png_path, digest_path = _snapshot_paths(plugin_name, case_name)

    if UPDATE_MODE:
        save_snapshot(image, plugin_name, case_name)
        return

    if not digest_path.exists():
        raise FileNotFoundError(
            f"No snapshot baseline found for {plugin_name}/{case_name}.\n"
            f"Expected digest at: {digest_path}\n"
            "Run `python scripts/update_snapshots.py` to capture a baseline."
        )

    expected_digest = digest_path.read_text().strip()
    actual_digest = _image_sha256(image)

    assert actual_digest == expected_digest, (
        f"Snapshot mismatch for {plugin_name}/{case_name}!\n"
        f"  Expected : {expected_digest}\n"
        f"  Got      : {actual_digest}\n"
        f"  Baseline : {png_path}\n"
        "If this change is intentional, run `python scripts/update_snapshots.py` "
        "to update the stored baseline."
    )
