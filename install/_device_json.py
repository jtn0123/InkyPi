#!/usr/bin/env python3
"""Safe mutation helper for install/config_base/device.json (JTN-701).

Replaces sed-based JSON mutation in install.sh. Uses json.load/json.dump,
preserves unrelated keys, writes atomically (temp file + os.replace), and
fails fast on malformed input instead of silently corrupting the file.

Usage:
    python3 install/_device_json.py set-display <display_type> --path <device.json>

Exit codes:
    0  success
    1  I/O error (missing file, permission denied)
    2  malformed JSON / invalid argument
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path


def set_display(path: Path, display_type: str) -> None:
    """Set top-level ``display_type`` key to ``display_type``, preserving all
    other keys and ordering, with an atomic temp-file + ``os.replace`` swap.

    Raises:
        FileNotFoundError: path does not exist.
        ValueError: file is not valid JSON or root is not an object.
    """
    raw = path.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{path}: not valid JSON ({exc.msg} at line {exc.lineno})"
        ) from exc

    if not isinstance(data, dict):
        raise ValueError(
            f"{path}: root must be a JSON object, got {type(data).__name__}"
        )

    data["display_type"] = display_type

    # Atomic write: tempfile in same directory, fsync, then os.replace.
    # Same-directory tempfile guarantees os.replace is a rename(2) on the
    # same filesystem (never a cross-device copy).
    directory = path.parent
    fd, tmp_path = tempfile.mkstemp(
        prefix=".device.json.", suffix=".tmp", dir=str(directory)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            # 2-space indent matches the repo style in install/config_base/device.json.
            # Trailing newline to keep POSIX text files well-formed.
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except Exception:
        # Best-effort cleanup; ignore cleanup failures since the original
        # exception is more important.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Safe device.json mutation helper (JTN-701)"
    )
    sub = p.add_subparsers(dest="command", required=True)

    set_disp = sub.add_parser("set-display", help="Set the display_type field")
    set_disp.add_argument(
        "display_type", help="Display model identifier (e.g. epd7in3e)"
    )
    set_disp.add_argument(
        "--path", required=True, type=Path, help="Path to device.json"
    )

    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.command == "set-display":
        if not args.display_type or not args.display_type.strip():
            print("error: display_type must be non-empty", file=sys.stderr)
            return 2
        if not args.path.is_file():
            print(f"error: {args.path}: not a file", file=sys.stderr)
            return 1
        try:
            set_display(args.path, args.display_type)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        except OSError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"Set display_type={args.display_type} in {args.path}")
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
