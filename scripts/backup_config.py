#!/usr/bin/env python3
"""
Backup InkyPi device configuration and plugin instance images to a tar.gz archive.

Usage:
    python scripts/backup_config.py [--output PATH] [--include-history]
                                    [--config-dir PATH] [--instances-dir PATH]
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import tarfile
from datetime import UTC, datetime

BACKUP_FORMAT_VERSION = "1"


def _default_output_path() -> str:
    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"inkypi-backup-{ts}.tar.gz"


def _detect_instances_dir() -> str:
    """Auto-detect plugin images directory relative to this script."""
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(scripts_dir)
    return os.path.join(project_root, "src", "static", "images", "plugins")


def _detect_config_dir() -> str:
    """Detect default config directory relative to this script."""
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(scripts_dir)
    return os.path.join(project_root, "src", "config")


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _collect_files(
    config_dir: str,
    instances_dir: str,
    include_history: bool,
    history_dir: str | None,
) -> list[tuple[str, str]]:
    """Return list of (filesystem_path, archive_name) tuples."""
    entries: list[tuple[str, str]] = []

    # Config JSON files
    if os.path.isdir(config_dir):
        for name in sorted(os.listdir(config_dir)):
            if name.endswith(".json"):
                full = os.path.join(config_dir, name)
                if os.path.isfile(full):
                    entries.append((full, os.path.join("config", name)))

    # Plugin instance images directory (recursive)
    if os.path.isdir(instances_dir):
        for dirpath, _dirnames, filenames in os.walk(instances_dir):
            for fname in sorted(filenames):
                full = os.path.join(dirpath, fname)
                rel = os.path.relpath(full, os.path.dirname(instances_dir))
                entries.append((full, os.path.join("instances", rel)))

    # History images (optional)
    if include_history and history_dir and os.path.isdir(history_dir):
        for dirpath, _dirnames, filenames in os.walk(history_dir):
            for fname in sorted(filenames):
                full = os.path.join(dirpath, fname)
                rel = os.path.relpath(full, os.path.dirname(history_dir))
                entries.append((full, os.path.join("history", rel)))

    return entries


def _build_manifest(
    timestamp: str,
    entries: list[tuple[str, str]],
    device_json_path: str | None,
) -> dict:
    manifest: dict = {
        "backup_version": BACKUP_FORMAT_VERSION,
        "timestamp": timestamp,
        "included_paths": [arc for _fs, arc in entries],
        "device_json_checksum": None,
    }
    if device_json_path and os.path.isfile(device_json_path):
        manifest["device_json_checksum"] = _sha256_file(device_json_path)
    return manifest


def run_backup(
    output: str,
    config_dir: str,
    instances_dir: str,
    include_history: bool,
    history_dir: str | None = None,
) -> int:
    """Perform backup and return exit code."""
    timestamp = datetime.now(tz=UTC).isoformat()
    entries = _collect_files(config_dir, instances_dir, include_history, history_dir)

    device_json_path = os.path.join(config_dir, "device.json")
    manifest = _build_manifest(timestamp, entries, device_json_path)
    manifest_json = json.dumps(manifest, indent=2).encode("utf-8")

    output = os.path.abspath(output)
    os.makedirs(
        os.path.dirname(output) if os.path.dirname(output) else ".", exist_ok=True
    )

    with tarfile.open(output, "w:gz") as tar:
        # Write manifest first
        manifest_info = tarfile.TarInfo(name="manifest.json")
        manifest_info.size = len(manifest_json)
        tar.addfile(manifest_info, io.BytesIO(manifest_json))

        # Write collected files
        for fs_path, arc_name in entries:
            tar.add(fs_path, arcname=arc_name)

    total_size = os.path.getsize(output)
    file_count = len(entries)
    size_kb = total_size / 1024

    print(f"Backup complete: {output}")
    print(f"  Files archived : {file_count}")
    print(f"  Archive size   : {size_kb:.1f} KB")
    if manifest["device_json_checksum"]:
        print(f"  device.json SHA256: {manifest['device_json_checksum']}")

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Back up InkyPi device config and plugin instance images.",
    )
    parser.add_argument(
        "--output",
        default=None,
        metavar="PATH",
        help="Output tar.gz path (default: ./inkypi-backup-<timestamp>.tar.gz)",
    )
    parser.add_argument(
        "--include-history",
        action="store_true",
        default=False,
        help="Include history images in backup (default: off — may be large)",
    )
    parser.add_argument(
        "--config-dir",
        default=None,
        metavar="PATH",
        help="Path to config directory (default: src/config)",
    )
    parser.add_argument(
        "--instances-dir",
        default=None,
        metavar="PATH",
        help="Path to plugin instance images directory (default: auto-detected)",
    )
    args = parser.parse_args(argv)

    output = args.output or _default_output_path()
    config_dir = args.config_dir or _detect_config_dir()
    instances_dir = args.instances_dir or _detect_instances_dir()

    # Derive history dir from instances_dir sibling
    history_dir = os.path.join(os.path.dirname(instances_dir), "history")

    return run_backup(
        output=output,
        config_dir=config_dir,
        instances_dir=instances_dir,
        include_history=args.include_history,
        history_dir=history_dir,
    )


if __name__ == "__main__":
    sys.exit(main())
