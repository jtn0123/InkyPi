#!/usr/bin/env python3
"""
Collect a diagnostic snapshot tarball for InkyPi support workflows.

Usage:
    python scripts/diagnostic_snapshot.py [--output PATH] [--config-dir PATH]
                                          [--log-path PATH] [--log-lines N]
"""

from __future__ import annotations

import argparse
import io
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
from datetime import UTC, datetime

SNAPSHOT_FORMAT_VERSION = "1"

# Key name substrings that should be redacted (case-insensitive).
_SECRET_SUBSTRINGS = ("api_key", "token", "password", "secret", "pin")


def _default_output_path() -> str:
    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"inkypi-diag-{ts}.tar.gz"


def _detect_config_dir() -> str:
    """Detect default config directory relative to this script."""
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(scripts_dir)
    return os.path.join(project_root, "src", "config")


def _detect_log_path() -> str | None:
    """Return the first plausible log file path, or None."""
    candidates = [
        os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "inkypi.log"
        ),
        "/var/log/inkypi.log",
        "/tmp/inkypi.log",
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def _collect_system_info() -> str:
    """Return a multi-section string with system information."""
    lines: list[str] = []

    # Platform / uname
    lines.append("=== uname ===")
    uname = platform.uname()
    lines.append(f"system   : {uname.system}")
    lines.append(f"node     : {uname.node}")
    lines.append(f"release  : {uname.release}")
    lines.append(f"version  : {uname.version}")
    lines.append(f"machine  : {uname.machine}")
    lines.append(f"processor: {uname.processor}")
    lines.append("")

    # Disk usage
    lines.append("=== disk usage (/) ===")
    try:
        usage = shutil.disk_usage("/")
        lines.append(f"total : {usage.total // (1024 ** 3)} GB")
        lines.append(f"used  : {usage.used // (1024 ** 3)} GB")
        lines.append(f"free  : {usage.free // (1024 ** 3)} GB")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"(unavailable: {exc})")
    lines.append("")

    # Memory — try psutil first, fall back to /proc/meminfo
    lines.append("=== memory ===")
    _collected_memory = False
    try:
        import psutil  # type: ignore[import-not-found]

        vm = psutil.virtual_memory()
        lines.append(f"total    : {vm.total // (1024 ** 2)} MB")
        lines.append(f"available: {vm.available // (1024 ** 2)} MB")
        lines.append(f"used     : {vm.used // (1024 ** 2)} MB")
        lines.append(f"percent  : {vm.percent}%")
        _collected_memory = True
    except ImportError:
        pass

    if not _collected_memory:
        meminfo_path = "/proc/meminfo"
        if os.path.isfile(meminfo_path):
            try:
                with open(meminfo_path) as f:
                    lines += [
                        line.rstrip()
                        for line in f
                        if any(
                            k in line for k in ("MemTotal", "MemFree", "MemAvailable")
                        )
                    ]
                _collected_memory = True
            except OSError:
                pass

    if not _collected_memory:
        lines.append(
            "(memory info unavailable — psutil not installed and /proc/meminfo not found)"
        )
    lines.append("")

    # Python version
    lines.append("=== python ===")
    lines.append(f"version: {sys.version}")
    lines.append(f"executable: {sys.executable}")
    lines.append("")

    # pip freeze
    lines.append("=== pip freeze ===")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "freeze"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            lines.append(result.stdout.strip() or "(no packages)")
        else:
            lines.append(f"(pip freeze failed: {result.stderr.strip()})")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"(pip freeze unavailable: {exc})")

    return "\n".join(lines) + "\n"


def _is_secret_key(key: str) -> bool:
    """Return True if the key name suggests it holds a secret value."""
    lower = key.lower()
    return any(sub in lower for sub in _SECRET_SUBSTRINGS)


def _redact_dict(obj: object) -> object:
    """Recursively redact secret-looking values in a JSON-decoded structure."""
    if isinstance(obj, dict):
        return {
            k: "***REDACTED***" if _is_secret_key(k) else _redact_dict(v)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_redact_dict(item) for item in obj]
    return obj


def _collect_redacted_config(config_dir: str) -> bytes:
    """Return JSON bytes for a redacted copy of device.json."""
    device_json = os.path.join(config_dir, "device.json")
    if not os.path.isfile(device_json):
        return json.dumps({"error": "device.json not found"}, indent=2).encode("utf-8")
    try:
        with open(device_json) as f:
            data = json.load(f)
        redacted = _redact_dict(data)
        return json.dumps(redacted, indent=2).encode("utf-8")
    except Exception as exc:  # noqa: BLE001
        return json.dumps(
            {"error": f"could not read device.json: {exc}"}, indent=2
        ).encode("utf-8")


def _collect_log_tail(log_path: str | None, log_lines: int) -> str | None:
    """Return the last *log_lines* lines of the log file, or None if unavailable."""
    if not log_path:
        return None
    if not os.path.isfile(log_path):
        return None
    try:
        with open(log_path, errors="replace") as f:
            all_lines = f.readlines()
        tail = all_lines[-log_lines:]
        header = f"--- last {log_lines} lines of {log_path} ---\n"
        return header + "".join(tail)
    except OSError:
        return None


def _collect_journal(lines: int = 200) -> str | None:
    """Best-effort: grab recent journal entries via journalctl."""
    try:
        result = subprocess.run(
            ["journalctl", "-u", "inkypi", "--no-pager", f"-n{lines}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    except Exception:  # noqa: BLE001
        pass

    # Fallback: try without unit filter
    try:
        result = subprocess.run(
            ["journalctl", "--no-pager", "-n50"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return "--- recent journal (no inkypi unit filter) ---\n" + result.stdout
    except Exception:  # noqa: BLE001
        pass

    return None


def run_snapshot(
    output: str,
    config_dir: str,
    log_path: str | None,
    log_lines: int,
) -> int:
    """Collect diagnostic snapshot and write tarball. Returns exit code."""
    timestamp = datetime.now(tz=UTC).isoformat()

    # Collect all content in memory
    system_info = _collect_system_info().encode("utf-8")
    redacted_config = _collect_redacted_config(config_dir)
    log_tail_str = _collect_log_tail(log_path, log_lines)
    journal_str = _collect_journal()

    included_files: list[str] = ["system_info.txt", "config_redacted.json"]
    if log_tail_str is not None:
        included_files.append("recent_logs.txt")
    if journal_str is not None:
        included_files.append("journal.txt")
    included_files.append("manifest.json")

    manifest = {
        "snapshot_version": SNAPSHOT_FORMAT_VERSION,
        "timestamp": timestamp,
        "files": included_files,
    }
    manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")

    output = os.path.abspath(output)
    out_dir = os.path.dirname(output)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    def _add_bytes(tar: tarfile.TarFile, name: str, data: bytes) -> None:
        info = tarfile.TarInfo(name=name)
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))

    with tarfile.open(output, "w:gz") as tar:
        _add_bytes(tar, "system_info.txt", system_info)
        _add_bytes(tar, "config_redacted.json", redacted_config)
        if log_tail_str is not None:
            _add_bytes(tar, "recent_logs.txt", log_tail_str.encode("utf-8"))
        if journal_str is not None:
            _add_bytes(tar, "journal.txt", journal_str.encode("utf-8"))
        _add_bytes(tar, "manifest.json", manifest_bytes)

    total_size = os.path.getsize(output)
    size_kb = total_size / 1024

    print(f"Diagnostic snapshot: {output}")
    print(f"  Files in tarball : {len(included_files)}")
    print(f"  Archive size     : {size_kb:.1f} KB")
    print(f"  Timestamp        : {timestamp}")

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Collect a diagnostic snapshot tarball for InkyPi support.",
    )
    parser.add_argument(
        "--output",
        default=None,
        metavar="PATH",
        help="Output tar.gz path (default: ./inkypi-diag-<timestamp>.tar.gz)",
    )
    parser.add_argument(
        "--config-dir",
        default=None,
        metavar="PATH",
        help="Path to config directory containing device.json (default: src/config)",
    )
    parser.add_argument(
        "--log-path",
        default=None,
        metavar="PATH",
        help="Path to inkypi.log (default: auto-detect)",
    )
    parser.add_argument(
        "--log-lines",
        default=500,
        type=int,
        metavar="N",
        help="Number of log tail lines to include (default: 500)",
    )
    args = parser.parse_args(argv)

    output = args.output or _default_output_path()
    config_dir = args.config_dir or _detect_config_dir()
    log_path = args.log_path or _detect_log_path()

    return run_snapshot(
        output=output,
        config_dir=config_dir,
        log_path=log_path,
        log_lines=args.log_lines,
    )


if __name__ == "__main__":
    sys.exit(main())
