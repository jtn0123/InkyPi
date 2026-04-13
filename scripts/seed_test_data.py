#!/usr/bin/env python3
"""
Populate a dev InkyPi environment with sample plugin instances, playlists,
and history images + sidecar JSON files.

Usage:
    python scripts/seed_test_data.py --target-dir /tmp/inkypi-dev \\
        [--count 20] [--reset]

Safety:
    Refuses to run if --target-dir resolves to anywhere under src/config, or
    if a device.json found there has no dev marker (display_type != "mock").
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
_SRC_CONFIG = (_PROJECT_ROOT / "src" / "config").resolve()

# History image dimensions matching default InkyPi resolution
_IMG_WIDTH = 800
_IMG_HEIGHT = 480

# Palette of solid colours for synthetic history images
_COLOURS = [
    (30, 144, 255),  # dodger-blue
    (255, 99, 71),  # tomato
    (60, 179, 113),  # medium-sea-green
    (255, 215, 0),  # gold
    (147, 112, 219),  # medium-purple
    (255, 165, 0),  # orange
    (64, 224, 208),  # turquoise
    (220, 20, 60),  # crimson
    (0, 191, 255),  # deep-sky-blue
    (154, 205, 50),  # yellow-green
]

# Sample plugin instances to seed
_SAMPLE_PLUGINS = [
    {
        "plugin_id": "year_progress",
        "name": "Year Progress",
        "plugin_settings": {
            "style": "bar",
            "show_percentage": True,
            "show_days_remaining": True,
        },
        "refresh": {"interval": 3600},
        "latest_refresh_time": None,
    },
    {
        "plugin_id": "weather",
        "name": "Weather",
        "plugin_settings": {
            "weatherProvider": "OpenMeteo",
            "location": "New York, NY",
            "latitude": "40.7128",
            "longitude": "-74.0060",
            "unit": "fahrenheit",
            "apiKey": "PLACEHOLDER_API_KEY",
        },
        "refresh": {"interval": 1800},
        "latest_refresh_time": None,
    },
    {
        "plugin_id": "calendar",
        "name": "Calendar",
        "plugin_settings": {
            "calendarUrl": "https://example.com/calendar.ics",
            "showWeekNumbers": False,
            "firstDayOfWeek": "monday",
            "maxEvents": 5,
        },
        "refresh": {"interval": 900},
        "latest_refresh_time": None,
    },
]

_SAMPLE_PLAYLIST = {
    "name": "Seed Playlist",
    "start_time": "00:00",
    "end_time": "24:00",
    "plugins": _SAMPLE_PLUGINS,
    "current_plugin_index": 0,
}

# ---------------------------------------------------------------------------
# Safety helpers
# ---------------------------------------------------------------------------


def _resolve(path: str) -> Path:
    return Path(path).expanduser().resolve()


def _is_under_src_config(target: Path) -> bool:
    """Return True if *target* is equal to or nested inside src/config."""
    try:
        target.relative_to(_SRC_CONFIG)
    except ValueError:
        return False
    return True


def _has_dev_marker(target: Path) -> bool:
    """
    Return True if the target directory looks like a dev environment.

    Heuristic: a device.json whose display_type is "mock" is a dev device.
    If no device.json exists at all we also allow seeding (empty target dir).
    """
    device_json = target / "device.json"
    if not device_json.exists():
        return True  # no config yet — safe to seed
    try:
        data = json.loads(device_json.read_text(encoding="utf-8"))
    except Exception:
        return False  # unreadable JSON — refuse
    # Refuse if dev key is explicitly False
    if data.get("dev") is False:
        return False
    # Refuse if display_type is a real hardware driver
    display_type = data.get("display_type", "")
    return not (display_type and display_type not in ("mock",))


def _safety_check(target: Path) -> None:
    """Raise SystemExit with a message if the target is unsafe."""
    if _is_under_src_config(target):
        sys.exit(
            f"ERROR: --target-dir resolves to {target}, which is under "
            f"src/config ({_SRC_CONFIG}). Refusing to seed production config."
        )
    if not _has_dev_marker(target):
        sys.exit(
            f"ERROR: {target}/device.json does not have a dev marker "
            "(display_type must be 'mock'). Refusing to seed."
        )


# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------


def _make_image(colour: tuple[int, int, int]):
    """Create a solid-colour 800x480 PIL Image."""
    try:
        from PIL import Image
    except ImportError:
        sys.exit("ERROR: Pillow is required. Install it with: pip install Pillow")
    return Image.new("RGB", (_IMG_WIDTH, _IMG_HEIGHT), colour)


def _ts_filename(dt: datetime) -> str:
    return f"display_{dt.strftime('%Y%m%d_%H%M%S')}"


def _seed_history(
    history_dir: Path,
    count: int,
    *,
    idempotent: bool = True,
) -> int:
    """Write *count* PNG + sidecar JSON pairs under *history_dir*.

    Returns the number of entries actually written (0 if already present and
    idempotent=True).
    """
    history_dir.mkdir(parents=True, exist_ok=True)

    # Idempotency marker: check for any seed-generated files
    existing = list(history_dir.glob("display_*.png"))
    if idempotent and existing:
        return 0

    now = datetime.now(tz=UTC)
    interval = timedelta(days=7) / max(count, 1)
    statuses = ["success", "success", "success", "failure"]  # 75% success

    written = 0
    for i in range(count):
        dt = now - timedelta(days=7) + interval * i
        stem = _ts_filename(dt)
        colour = _COLOURS[i % len(_COLOURS)]
        img = _make_image(colour)
        png_path = history_dir / f"{stem}.png"
        img.save(str(png_path), format="PNG")

        status = statuses[i % len(statuses)]
        plugin_id = _SAMPLE_PLUGINS[i % len(_SAMPLE_PLUGINS)]["plugin_id"]
        sidecar = {
            "plugin_id": plugin_id,
            "plugin_name": _SAMPLE_PLUGINS[i % len(_SAMPLE_PLUGINS)]["name"],
            "status": status,
            "timestamp": dt.isoformat(),
            "error": "Simulated failure for testing" if status == "failure" else None,
            "refresh_type": "Scheduled",
        }
        (history_dir / f"{stem}.json").write_text(
            json.dumps(sidecar, indent=2), encoding="utf-8"
        )
        written += 1

    return written


def _seed_device_config(
    target: Path,
    *,
    idempotent: bool = True,
) -> tuple[int, int]:
    """Write (or update) device.json with sample plugins + playlist.

    Returns (plugins_written, playlists_written).
    """
    device_json = target / "device.json"

    if device_json.exists():
        try:
            data = json.loads(device_json.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    else:
        data = {
            "name": "InkyPi Dev (seeded)",
            "display_type": "mock",
            "resolution": [800, 480],
            "orientation": "horizontal",
        }

    playlist_config = data.get("playlist_config", {})
    playlists = playlist_config.get("playlists", [])

    plugins_written = 0
    playlists_written = 0

    if idempotent:
        playlist_names = {p.get("name") for p in playlists}
        if _SAMPLE_PLAYLIST["name"] in playlist_names:
            return 0, 0

    playlists.append(_SAMPLE_PLAYLIST)
    playlist_config["playlists"] = playlists
    if not playlist_config.get("active_playlist"):
        playlist_config["active_playlist"] = _SAMPLE_PLAYLIST["name"]
    data["playlist_config"] = playlist_config

    target.mkdir(parents=True, exist_ok=True)
    device_json.write_text(json.dumps(data, indent=2), encoding="utf-8")

    plugins_written = len(_SAMPLE_PLUGINS)
    playlists_written = 1
    return plugins_written, playlists_written


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed a dev InkyPi environment with sample data.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--target-dir",
        required=True,
        metavar="PATH",
        help=(
            "Directory to seed (must NOT be src/config; must contain a "
            "device.json with display_type=mock or be empty)."
        ),
    )
    parser.add_argument(
        "--count",
        type=int,
        default=20,
        metavar="N",
        help="Number of synthetic history PNG+sidecar pairs to generate (default: 20).",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Wipe the target directory before seeding (non-idempotent full reset).",
    )
    return parser.parse_args(argv)


def run(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    target = _resolve(args.target_dir)
    _safety_check(target)

    if args.reset and target.exists():
        shutil.rmtree(target)
        print(f"Reset: wiped {target}")

    target.mkdir(parents=True, exist_ok=True)

    # Seed device config (plugins + playlist)
    plugins_written, playlists_written = _seed_device_config(
        target, idempotent=not args.reset
    )

    # Seed history
    history_dir = target / "history"
    history_written = _seed_history(history_dir, args.count, idempotent=not args.reset)

    # Summary
    print(f"Target:            {target}")
    print(f"Plugin instances:  {plugins_written}")
    print(f"Playlists:         {playlists_written}")
    print(f"History entries:   {history_written}")
    if plugins_written == 0 and playlists_written == 0 and history_written == 0:
        print("(already seeded — use --reset to re-seed)")


if __name__ == "__main__":
    run()
