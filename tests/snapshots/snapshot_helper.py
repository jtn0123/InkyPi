"""Snapshot helper for plugin image golden-file tests.

The baseline source of truth is the canonical PNG under
``tests/snapshots/<plugin>/<case>.png``. Assertions are pixel-based with a
small tolerance (configurable via env vars) and emit failure artifacts:

- actual image: ``tests/snapshots/actual/<plugin>/<case>.png``
- diff overlay: ``tests/snapshots/actual/<plugin>/<case>.diff.png``
- stats JSON: ``tests/snapshots/actual/<plugin>/<case>.diff.json``
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

_TRUTHY = {"1", "true", "yes"}
_SNAPSHOTS_ROOT = Path(__file__).parent
_ACTUAL_ROOT = _SNAPSHOTS_ROOT / "actual"


def _env_bool(name: str, default: str = "") -> bool:
    return os.getenv(name, default).strip().lower() in _TRUTHY


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)).strip())
    except (TypeError, ValueError):
        return default


def _update_mode_enabled() -> bool:
    return _env_bool("SNAPSHOT_UPDATE")


def _channel_threshold() -> int:
    return max(0, _env_int("SNAPSHOT_CHANNEL_THRESHOLD", 6))


def _max_changed_pct() -> float:
    # Percent, not fraction; 0.05 means 0.05% of pixels may exceed threshold.
    return max(0.0, _env_float("SNAPSHOT_MAX_CHANGED_PCT", 0.05))


def _snapshot_paths(plugin_name: str, case_name: str) -> tuple[Path, Path]:
    base = _SNAPSHOTS_ROOT / plugin_name / case_name
    return base.with_suffix(".png"), base.with_suffix(".sha256")


def _artifact_paths(plugin_name: str, case_name: str) -> tuple[Path, Path, Path]:
    base = _ACTUAL_ROOT / plugin_name / case_name
    return (
        base.with_suffix(".png"),
        base.with_suffix(".diff.png"),
        base.with_suffix(".diff.json"),
    )


def _image_sha256(image: Image.Image) -> str:
    fingerprint = (
        f"{image.mode}|{image.width}x{image.height}|".encode() + image.tobytes()
    )
    return hashlib.sha256(fingerprint).hexdigest()


def save_snapshot(image: Image.Image, plugin_name: str, case_name: str) -> None:
    png_path, digest_path = _snapshot_paths(plugin_name, case_name)
    png_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(png_path, format="PNG")
    digest_path.write_text(_image_sha256(image) + "\n", encoding="utf-8")


@dataclass(frozen=True)
class _DiffStats:
    total_pixels: int
    changed_pixels: int
    changed_pct: float
    max_channel_delta: int
    expected_size: tuple[int, int]
    actual_size: tuple[int, int]
    resized_actual: bool
    changed_mask: np.ndarray


def _compute_diff_stats(
    expected_image: Image.Image, actual_image: Image.Image, threshold: int
) -> _DiffStats:
    expected_rgb = expected_image.convert("RGB")
    actual_rgb = actual_image.convert("RGB")

    resized_actual = False
    if actual_rgb.size != expected_rgb.size:
        actual_rgb = actual_rgb.resize(expected_rgb.size, Image.Resampling.BICUBIC)
        resized_actual = True

    expected_arr = np.asarray(expected_rgb, dtype=np.int16)
    actual_arr = np.asarray(actual_rgb, dtype=np.int16)
    channel_delta = np.abs(expected_arr - actual_arr)
    per_pixel_max_delta = channel_delta.max(axis=2)
    changed_mask = per_pixel_max_delta > threshold

    total_pixels = int(changed_mask.size)
    changed_pixels = int(changed_mask.sum())
    changed_pct = (changed_pixels / total_pixels * 100.0) if total_pixels else 0.0
    max_channel_delta = int(per_pixel_max_delta.max()) if total_pixels else 0

    return _DiffStats(
        total_pixels=total_pixels,
        changed_pixels=changed_pixels,
        changed_pct=changed_pct,
        max_channel_delta=max_channel_delta,
        expected_size=expected_image.size,
        actual_size=actual_image.size,
        resized_actual=resized_actual,
        changed_mask=changed_mask,
    )


def _build_diff_overlay(
    expected_image: Image.Image, changed_mask: np.ndarray
) -> Image.Image:
    base = expected_image.convert("RGBA")
    overlay = Image.new("RGBA", base.size, (255, 0, 0, 0))
    alpha_mask = Image.fromarray((changed_mask.astype(np.uint8) * 160), mode="L")
    overlay.putalpha(alpha_mask)
    return Image.alpha_composite(base, overlay).convert("RGB")


def assert_image_snapshot(
    image: Image.Image,
    plugin_name: str,
    case_name: str,
) -> None:
    png_path, _digest_path = _snapshot_paths(plugin_name, case_name)
    actual_png, diff_png, stats_json = _artifact_paths(plugin_name, case_name)

    if _update_mode_enabled():
        save_snapshot(image, plugin_name, case_name)
        return

    if not png_path.exists():
        raise FileNotFoundError(
            f"No snapshot baseline found for {plugin_name}/{case_name}.\n"
            f"Expected PNG at: {png_path}\n"
            "Run `pytest tests/snapshots/ --update-snapshots` to capture baselines."
        )

    with Image.open(png_path) as baseline_image:
        expected_image = baseline_image.copy()
    threshold = _channel_threshold()
    max_changed_pct = _max_changed_pct()
    stats = _compute_diff_stats(expected_image, image, threshold)

    size_mismatch = stats.expected_size != stats.actual_size
    within_tolerance = stats.changed_pct <= max_changed_pct
    if not size_mismatch and within_tolerance:
        return

    actual_png.parent.mkdir(parents=True, exist_ok=True)
    image.save(actual_png, format="PNG")
    _build_diff_overlay(expected_image, stats.changed_mask).save(diff_png, format="PNG")

    stats_payload = {
        "plugin": plugin_name,
        "case": case_name,
        "threshold": threshold,
        "max_changed_pct": max_changed_pct,
        "total_pixels": stats.total_pixels,
        "changed_pixels": stats.changed_pixels,
        "changed_pct": round(stats.changed_pct, 6),
        "max_channel_delta": stats.max_channel_delta,
        "expected_size": list(stats.expected_size),
        "actual_size": list(stats.actual_size),
        "resized_actual_for_diff": stats.resized_actual,
        "size_mismatch": size_mismatch,
    }
    stats_json.write_text(json.dumps(stats_payload, indent=2) + "\n", encoding="utf-8")

    reasons = []
    if size_mismatch:
        reasons.append(
            f"size mismatch expected={stats.expected_size} actual={stats.actual_size}"
        )
    if not within_tolerance:
        reasons.append(
            f"{stats.changed_pct:.4f}% changed pixels exceeds allowed {max_changed_pct:.4f}% "
            f"(threshold={threshold})"
        )

    reason_block = "; ".join(reasons)
    raise AssertionError(
        f"Snapshot mismatch for {plugin_name}/{case_name}: {reason_block}\n"
        f"  Baseline : {png_path}\n"
        f"  Actual   : {actual_png}\n"
        f"  Diff     : {diff_png}\n"
        f"  Stats    : {stats_json}\n"
        "In CI these files are uploaded via the 'snapshot-failures' artifact.\n"
        "If this change is intentional, run `pytest tests/snapshots/ --update-snapshots`."
    )
