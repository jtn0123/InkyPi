#!/usr/bin/env python3
"""Dry-run a plugin offline — no display, no refresh task, no web server.

Loads a plugin by ID, calls generate_image() with a mock device config, and
writes the result to a PNG file. Useful for plugin development, debugging, and
CI smoke tests.

Usage examples (run from repo root):
  python scripts/dry_run_plugin.py --plugin year_progress
  python scripts/dry_run_plugin.py --plugin clock --width 640 --height 400
  python scripts/dry_run_plugin.py --plugin year_progress --config /tmp/my_settings.json
  python scripts/dry_run_plugin.py --plugin weather --output /tmp/weather.png
"""

import argparse
import json
import os
import sys
from time import perf_counter

# Ensure src/ is on the import path (script may be run from any directory)
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(REPO_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)


class _MockDeviceConfig:
    """Minimal device-config stub that satisfies BasePlugin.generate_image().

    Only the accessors used by the base plugin and most concrete plugins are
    implemented; everything else returns the supplied default.
    """

    def __init__(self, width: int, height: int, orientation: str, timezone: str):
        self._width = width
        self._height = height
        self._orientation = orientation
        self._timezone = timezone

    def get_resolution(self):
        return (self._width, self._height)

    def get_config(self, key, default=None):
        mapping: dict = {
            "orientation": self._orientation,
            "timezone": self._timezone,
            "time_format": "12h",
            "image_settings": {},
        }
        return mapping.get(key, default)

    def load_env_key(self, key: str):
        """Return the real env var so plugins that need keys can still work."""
        return os.environ.get(key)


def _discover_plugin_config(plugin_id: str) -> dict:
    """Read plugin-info.json from the plugin's source directory.

    Returns a minimal config dict suitable for passing to load_plugins().
    """
    plugins_dir = os.path.join(SRC_DIR, "plugins")
    info_path = os.path.join(plugins_dir, plugin_id, "plugin-info.json")
    if not os.path.isfile(info_path):
        sys.exit(
            f"ERROR: No plugin-info.json found for '{plugin_id}' at {info_path}\n"
            "Check that --plugin matches a directory name under src/plugins/."
        )
    with open(info_path, encoding="utf-8") as f:
        info = json.load(f)

    plugin_class = info.get("class")
    if not plugin_class:
        sys.exit(
            f"ERROR: plugin-info.json for '{plugin_id}' is missing the 'class' field."
        )

    return {
        "id": plugin_id,
        "class": plugin_class,
        "display_name": info.get("display_name", plugin_id),
        "api_version": info.get("api_version"),
        "version": info.get("version"),
    }


def _load_settings(config_path: str | None) -> dict:
    """Load plugin instance settings from a JSON file, or return empty dict."""
    if not config_path:
        return {}
    if not os.path.isfile(config_path):
        sys.exit(f"ERROR: --config path not found: {config_path}")
    with open(config_path, encoding="utf-8") as f:
        settings = json.load(f)
    if not isinstance(settings, dict):
        sys.exit(
            f"ERROR: --config file must contain a JSON object, got {type(settings)}"
        )
    return settings


def _default_output_path(plugin_id: str) -> str:
    from datetime import datetime

    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    return f"dry-run-{plugin_id}-{ts}.png"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dry-run a plugin offline and write the result to a PNG."
    )
    parser.add_argument(
        "--plugin",
        required=True,
        metavar="PLUGIN_ID",
        help="Plugin ID (directory name under src/plugins/), e.g. year_progress",
    )
    parser.add_argument(
        "--instance",
        metavar="NAME",
        default=None,
        help="(Informational) Instance name — logged but not used for rendering.",
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        default=None,
        help="Output PNG path. Defaults to ./dry-run-<plugin>-<timestamp>.png",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=800,
        help="Display width in pixels (default: 800)",
    )
    parser.add_argument(
        "--height",
        type=int,
        default=480,
        help="Display height in pixels (default: 480)",
    )
    parser.add_argument(
        "--orientation",
        default="horizontal",
        choices=["horizontal", "vertical"],
        help="Display orientation (default: horizontal)",
    )
    parser.add_argument(
        "--timezone",
        default="America/New_York",
        metavar="TZ",
        help="Timezone name passed to the plugin (default: America/New_York)",
    )
    parser.add_argument(
        "--config",
        metavar="PATH",
        default=None,
        help=(
            "Path to a JSON file containing plugin instance settings "
            "(key/value pairs). These override any device.json lookup."
        ),
    )
    args = parser.parse_args()

    plugin_id: str = args.plugin
    output_path: str = args.output or _default_output_path(plugin_id)
    instance_label: str = args.instance or plugin_id

    print(f"[dry-run] Plugin   : {plugin_id}")
    print(f"[dry-run] Instance : {instance_label}")
    print(f"[dry-run] Canvas   : {args.width}x{args.height} ({args.orientation})")
    print(f"[dry-run] Timezone : {args.timezone}")
    print(f"[dry-run] Output   : {output_path}")

    # Discover plugin metadata
    plugin_config = _discover_plugin_config(plugin_id)

    # Load plugin instance settings (may be empty)
    settings = _load_settings(args.config)
    if settings:
        print(f"[dry-run] Settings : {list(settings.keys())}")
    else:
        print("[dry-run] Settings : (none — using plugin defaults)")

    # Register the plugin with the registry so get_plugin_instance() works
    from plugins.plugin_registry import get_plugin_instance, load_plugins

    load_plugins([plugin_config])

    # Build a mock device config
    device_config = _MockDeviceConfig(
        width=args.width,
        height=args.height,
        orientation=args.orientation,
        timezone=args.timezone,
    )

    # Run generate_image() and time it
    print("[dry-run] Running generate_image()…")
    t0 = perf_counter()
    plugin_instance = get_plugin_instance(plugin_config)
    image = plugin_instance.generate_image(settings, device_config)
    elapsed_ms = int((perf_counter() - t0) * 1000)

    if image is None:
        sys.exit("ERROR: Plugin returned None instead of an image.")

    # Save the result
    out_dir = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(out_dir, exist_ok=True)
    image.save(output_path)

    print(f"[dry-run] Done in {elapsed_ms} ms")
    print(f"[dry-run] Image size : {image.width}x{image.height} px")
    print(f"[dry-run] Saved to   : {os.path.abspath(output_path)}")


if __name__ == "__main__":
    main()
