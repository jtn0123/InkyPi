#!/usr/bin/env python3
"""
Restore InkyPi device configuration and plugin instance images from a backup archive.

Usage:
    python scripts/restore_config.py BACKUP_PATH [--config-dir PATH]
                                     [--instances-dir PATH] [--yes]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tarfile
from datetime import UTC, datetime


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


def _read_manifest(tar: tarfile.TarFile) -> dict:
    """Extract and parse manifest.json from an open tarfile."""
    try:
        member = tar.getmember("manifest.json")
    except KeyError as exc:
        raise ValueError("No manifest.json found in backup archive") from exc
    fobj = tar.extractfile(member)
    if fobj is None:
        raise ValueError("manifest.json is not a regular file")
    return json.loads(fobj.read().decode("utf-8"))


def _pre_restore_backup(config_dir: str, instances_dir: str) -> str:
    """Create a safety backup of current state before overwriting."""
    # Import inline so the module stays self-contained
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, scripts_dir)
    try:
        import backup_config  # noqa: PLC0415
    finally:
        sys.path.pop(0)

    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    output = os.path.abspath(f".pre-restore-{ts}.tar.gz")
    history_dir = os.path.join(os.path.dirname(instances_dir), "history")
    backup_config.run_backup(
        output=output,
        config_dir=config_dir,
        instances_dir=instances_dir,
        include_history=False,
        history_dir=history_dir,
    )
    return output


def _extract_backup(
    backup_path: str,
    config_dir: str,
    instances_dir: str,
) -> None:
    """Extract backup archive contents into the correct destination directories."""
    instances_parent = os.path.dirname(instances_dir)

    with tarfile.open(backup_path, "r:gz") as tar:
        for member in tar.getmembers():
            name = member.name
            if name == "manifest.json":
                continue

            if name.startswith("config/"):
                rel = name[len("config/") :]
                dest = os.path.join(config_dir, rel)
            elif name.startswith("instances/"):
                rel = name[len("instances/") :]
                dest = os.path.join(instances_parent, rel)
            elif name.startswith("history/"):
                rel = name[len("history/") :]
                dest = os.path.join(instances_parent, rel)
            else:
                # Unknown prefix — skip
                continue

            if member.isdir():
                os.makedirs(dest, exist_ok=True)
                continue

            os.makedirs(os.path.dirname(dest), exist_ok=True)
            fobj = tar.extractfile(member)
            if fobj is not None:
                with open(dest, "wb") as out:
                    out.write(fobj.read())


def run_restore(
    backup_path: str,
    config_dir: str,
    instances_dir: str,
    yes: bool = False,
    _input_fn=input,
) -> int:
    """Perform restore and return exit code."""
    backup_path = os.path.abspath(backup_path)
    if not os.path.isfile(backup_path):
        print(f"Error: backup file not found: {backup_path}", file=sys.stderr)
        return 1

    # Read manifest and show summary
    try:
        with tarfile.open(backup_path, "r:gz") as tar:
            manifest = _read_manifest(tar)
    except (tarfile.TarError, ValueError, json.JSONDecodeError) as exc:
        print(f"Error reading backup archive: {exc}", file=sys.stderr)
        return 1

    print(f"Backup archive : {backup_path}")
    print(f"Backup version : {manifest.get('backup_version', 'unknown')}")
    print(f"Backup timestamp: {manifest.get('timestamp', 'unknown')}")
    paths = manifest.get("included_paths", [])
    print(f"Files to restore: {len(paths)}")
    print(f"  Config dir     : {config_dir}")
    print(f"  Instances dir  : {instances_dir}")

    if not yes:
        try:
            answer = (
                _input_fn(
                    "\nThis will overwrite current config and plugin images. "
                    "A safety backup will be created first.\nProceed? [y/N] "
                )
                .strip()
                .lower()
            )
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            return 1
        if answer not in ("y", "yes"):
            print("Aborted.")
            return 1

    # Create safety backup of current state
    print("\nCreating pre-restore safety backup...")
    try:
        safety_path = _pre_restore_backup(config_dir, instances_dir)
        print(f"Safety backup saved to: {safety_path}")
    except Exception as exc:  # noqa: BLE001
        print(f"Warning: could not create safety backup: {exc}", file=sys.stderr)

    # Extract
    print("Restoring files...")
    try:
        _extract_backup(backup_path, config_dir, instances_dir)
    except (tarfile.TarError, OSError) as exc:
        print(f"Error extracting backup: {exc}", file=sys.stderr)
        return 1

    # Verify device.json checksum
    expected_checksum = manifest.get("device_json_checksum")
    if expected_checksum:
        device_json_path = os.path.join(config_dir, "device.json")
        if os.path.isfile(device_json_path):
            actual = _sha256_file(device_json_path)
            if actual != expected_checksum:
                print(
                    f"Error: device.json checksum mismatch!\n"
                    f"  Expected: {expected_checksum}\n"
                    f"  Actual  : {actual}",
                    file=sys.stderr,
                )
                return 1
            print(f"Checksum verified: device.json OK ({actual[:16]}...)")
        else:
            print("Warning: device.json not found after restore", file=sys.stderr)

    print("Restore complete.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Restore InkyPi device config and plugin instance images from a backup.",
    )
    parser.add_argument(
        "backup_path",
        metavar="BACKUP_PATH",
        help="Path to the .tar.gz backup file",
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
    parser.add_argument(
        "--yes",
        action="store_true",
        default=False,
        help="Skip confirmation prompt",
    )
    args = parser.parse_args(argv)

    config_dir = args.config_dir or _detect_config_dir()
    instances_dir = args.instances_dir or _detect_instances_dir()

    return run_restore(
        backup_path=args.backup_path,
        config_dir=config_dir,
        instances_dir=instances_dir,
        yes=args.yes,
    )


if __name__ == "__main__":
    sys.exit(main())
