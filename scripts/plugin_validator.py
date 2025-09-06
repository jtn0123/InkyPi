#!/usr/bin/env python3

import argparse
import json
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = BASE_DIR / "src"
PLUGINS_DIR = SRC_DIR / "plugins"

sys.path.insert(0, str(SRC_DIR))


def validate_plugin_folder(plugin_dir: Path) -> list[str]:
    errors: list[str] = []

    info_path = plugin_dir / "plugin-info.json"
    if not info_path.is_file():
        errors.append(f"Missing plugin-info.json in {plugin_dir}")
        return errors

    try:
        info = json.loads(info_path.read_text())
    except Exception as exc:
        errors.append(f"Invalid JSON in {info_path}: {exc}")
        return errors

    plugin_id = info.get("id")
    class_name = info.get("class")
    if not plugin_id or not isinstance(plugin_id, str):
        errors.append("plugin-info.json must include string field 'id'")
    if not class_name or not isinstance(class_name, str):
        errors.append("plugin-info.json must include string field 'class'")

    # Verify module file exists
    if plugin_id:
        module_path = plugin_dir / f"{plugin_id}.py"
        if not module_path.is_file():
            errors.append(f"Missing module file: {module_path}")
        else:
            # Try to import and get class
            module_name = f"plugins.{plugin_id}.{plugin_id}"
            try:
                mod = __import__(module_name, fromlist=[class_name])
                cls = getattr(mod, class_name, None)
                if cls is None:
                    errors.append(
                        f"Class '{class_name}' not found in module {module_name}"
                    )
            except Exception as exc:
                errors.append(f"Failed to import {module_name}: {exc}")

    # Optional but recommended files
    settings_html = plugin_dir / "settings.html"
    render_dir = plugin_dir / "render"
    if not settings_html.is_file():
        # Not strictly required but warn
        errors.append("Warning: settings.html not found (plugin may not be configurable)")
    if not render_dir.is_dir():
        errors.append(
            "Warning: render/ directory not found (plugin may not use HTML renderer)"
        )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate InkyPi plugins")
    parser.add_argument(
        "plugin",
        nargs="?",
        help="Plugin ID to validate (defaults to all)",
    )
    args = parser.parse_args()

    targets: list[Path] = []
    if args.plugin:
        targets = [PLUGINS_DIR / args.plugin]
    else:
        targets = [p for p in PLUGINS_DIR.iterdir() if p.is_dir() and p.name != "__pycache__"]

    overall_errors = 0
    for plugin_dir in sorted(targets):
        errs = validate_plugin_folder(plugin_dir)
        header = f"[{plugin_dir.name}]"
        if errs:
            print(header)
            for e in errs:
                print(f" - {e}")
            overall_errors += len([e for e in errs if not e.startswith("Warning:")])
        else:
            print(f"{header} OK")

    return 1 if overall_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())


