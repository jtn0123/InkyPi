#!/usr/bin/env python3
"""Pre-flight abort gates for the updater.

``do_update.sh`` runs this before ``git checkout`` and ``update.sh`` runs it
before stopping the service or installing anything. A warning that scrolls past
in update output is not a gate; a non-zero exit here is. Every check is
read-only, so an abort leaves the device exactly as it was.

Checks:

* free disk space on the install filesystem(s) is at least ``--min-free-mb``
  (default 500, override with ``INKYPI_UPDATE_MIN_FREE_MB``; ``0`` disables)
* ``VERSION`` is readable and non-empty (``--version-file -`` reads stdin, so
  ``do_update.sh`` can pipe in the *target* tag's VERSION via ``git show``)
* the device config parses and passes ``utils.config_schema`` validation, the
  same validator the app runs at startup
* the display driver for the configured panel is present: ``mock`` always
  passes, ``inky`` needs the ``inky`` package importable, ``epd*in*`` needs the
  Waveshare driver module on disk and pinned in ``install/waveshare-manifest.txt``

Usage:
    python3 install/_preflight.py --repo-dir <repo> [--version-file PATH|-]
        [--config PATH] [--disk-path PATH ...] [--min-free-mb N]

Each failure prints one ``PREFLIGHT FAIL: <reason>`` line on stderr; the shell
caller records the first one in ``.last-update-failure``.

Exit codes:
    0  all checks passed
    3  at least one check failed
"""

from __future__ import annotations

import argparse
import fnmatch
import importlib.util
import json
import os
import re
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

EXIT_OK = 0
EXIT_FAILED = 3

DEFAULT_MIN_FREE_MB = 500
MIN_FREE_MB_ENV = "INKYPI_UPDATE_MIN_FREE_MB"

# Mirrors display.waveshare_display._WAVESHARE_DISPLAY_RE. Duplicated rather
# than imported because that module pulls in Pillow, and this helper must run
# under a bare system python3 when the venv is unusable.
_WAVESHARE_DISPLAY_RE = re.compile(r"^epd[A-Za-z0-9_]+$", re.ASCII)


class PreflightError(Exception):
    """A gate failed; the message is the user-facing reason."""


def _min_free_mb_default() -> int:
    raw = os.environ.get(MIN_FREE_MB_ENV, "").strip()
    if raw.isdigit():
        return int(raw)
    return DEFAULT_MIN_FREE_MB


def _existing_ancestor(path: Path) -> Path:
    """Nearest existing ancestor of *path* (disk usage needs a real path)."""
    current = path.absolute()
    while not current.exists() and current != current.parent:
        current = current.parent
    return current


def check_disk_space(paths: list[Path], min_free_mb: int) -> str:
    if min_free_mb <= 0:
        return "disk space check disabled"
    seen_devices: set[int] = set()
    reports: list[str] = []
    for raw in paths:
        path = _existing_ancestor(raw)
        try:
            device = path.stat().st_dev
            free_mb = shutil.disk_usage(path).free // (1024 * 1024)
        except OSError as exc:
            raise PreflightError(
                f"cannot read free disk space on {raw}: {exc}"
            ) from exc
        if device in seen_devices:
            continue
        seen_devices.add(device)
        if free_mb < min_free_mb:
            raise PreflightError(
                f"only {free_mb} MB free on the filesystem holding {raw} "
                f"(need {min_free_mb} MB; set {MIN_FREE_MB_ENV} to override)"
            )
        reports.append(f"{free_mb} MB free on {raw}")
    return "; ".join(reports)


def check_version(version_file: str) -> str:
    label = "target VERSION" if version_file == "-" else version_file
    try:
        if version_file == "-":
            text = sys.stdin.read()
        else:
            text = Path(version_file).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise PreflightError(f"{label} is unreadable: {exc}") from exc
    version = text.strip()
    if not version:
        raise PreflightError(f"{label} is empty or missing")
    return f"version {version}"


def resolve_config_path(repo_dir: Path, explicit: str | None) -> Path | None:
    """Pick the config the app would load (see Config._determine_config_path)."""
    if explicit:
        return Path(explicit)
    env_file = os.environ.get("INKYPI_CONFIG_FILE", "").strip()
    if env_file and os.path.isfile(env_file):
        return Path(env_file)
    config_dir = repo_dir / "src" / "config"
    for name in ("device.json", "device_dev.json"):
        candidate = config_dir / name
        if candidate.is_file():
            return candidate
    return None


def _load_validator(repo_dir: Path) -> Callable[[dict[str, Any]], None]:
    src_dir = str(repo_dir / "src")
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)
    try:
        from utils.config_schema import validate_device_config
    except Exception as exc:  # pragma: no cover - broken checkout
        raise PreflightError(
            f"cannot load the config validator from {src_dir}: {exc}"
        ) from exc
    return validate_device_config


def load_and_validate_config(repo_dir: Path, config_path: Path) -> dict[str, Any]:
    try:
        raw = config_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise PreflightError(f"cannot read {config_path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PreflightError(
            f"{config_path} is not valid JSON ({exc.msg} at line {exc.lineno})"
        ) from exc
    if not isinstance(data, dict):
        raise PreflightError(f"{config_path} must contain a JSON object")
    validate = _load_validator(repo_dir)
    try:
        validate(data)
    except ValueError as exc:
        raise PreflightError(f"{config_path}: {exc}") from exc
    return data


def _manifest_drivers(manifest: Path) -> set[str]:
    """Driver module names pinned in the manifest (mirrors waveshare_display)."""
    names: set[str] = set()
    try:
        lines = manifest.read_text(encoding="utf-8").splitlines()
    except OSError:
        return names
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        driver = line.split(maxsplit=1)[0]
        if driver.endswith(".py") and driver != "epdconfig.py":
            names.add(driver[:-3])
    return names


def check_display_driver(repo_dir: Path, config: dict[str, Any]) -> str:
    # DisplayManager defaults to "inky" when display_type is absent.
    display_type = str(config.get("display_type") or "inky")
    if display_type == "mock":
        return "display mock"
    if display_type == "inky":
        if importlib.util.find_spec("inky") is None:
            raise PreflightError(
                "display_type is 'inky' but the inky package is not importable "
                "in the app's Python environment"
            )
        return "display inky (inky package present)"
    if not fnmatch.fnmatch(display_type, "epd*in*"):
        raise PreflightError(f"unsupported display_type {display_type!r}")
    if not _WAVESHARE_DISPLAY_RE.fullmatch(display_type):
        raise PreflightError(f"invalid Waveshare display_type {display_type!r}")
    manifest = repo_dir / "install" / "waveshare-manifest.txt"
    pinned = _manifest_drivers(manifest)
    # Same rule as the runtime: an unreadable/empty manifest does not restrict.
    if pinned and display_type not in pinned:
        raise PreflightError(
            f"Waveshare driver {display_type!r} is not pinned in {manifest}"
        )
    driver_dir = repo_dir / "src" / "display" / "waveshare_epd"
    for module in (f"{display_type}.py", "epdconfig.py"):
        if not (driver_dir / module).is_file():
            raise PreflightError(
                f"Waveshare driver file {driver_dir / module} is missing "
                f"(re-run install.sh -W {display_type} to fetch it)"
            )
    return f"display {display_type} (driver present)"


def run_checks(args: argparse.Namespace) -> list[str]:
    """Run every gate and return the failure reasons (empty means pass)."""
    repo_dir = Path(args.repo_dir)
    failures: list[str] = []

    def gate(name: str, fn: Callable[[], str]) -> None:
        try:
            print(f"preflight {name}: ok ({fn()})")
        except PreflightError as exc:
            failures.append(str(exc))

    disk_paths = [repo_dir, *(Path(p) for p in args.disk_path)]
    gate("disk", lambda: check_disk_space(disk_paths, args.min_free_mb))
    gate("version", lambda: check_version(args.version_file))

    config_path = resolve_config_path(repo_dir, args.config)
    if config_path is None:
        # The app bootstraps device.json from install/config_base on first
        # start and install.sh owns choosing the panel, so with no config yet
        # there is nothing an update can break.
        print("preflight config: skipped (no device config yet)")
        return failures
    try:
        config = load_and_validate_config(repo_dir, config_path)
        print(f"preflight config: ok ({config_path})")
    except PreflightError as exc:
        failures.append(str(exc))
    else:
        # Only meaningful once the config is known-good: a broken config has
        # no trustworthy display_type to check.
        gate("display", lambda: check_display_driver(repo_dir, config))

    return failures


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="InkyPi updater pre-flight gates")
    p.add_argument("--repo-dir", required=True, help="InkyPi git checkout")
    p.add_argument(
        "--version-file",
        default=None,
        help="VERSION file to check, or '-' for stdin (default: <repo>/VERSION)",
    )
    p.add_argument("--config", default=None, help="device config to validate")
    p.add_argument(
        "--disk-path",
        action="append",
        default=[],
        help="additional path whose filesystem needs free space (repeatable)",
    )
    p.add_argument(
        "--min-free-mb",
        type=int,
        default=None,
        help=f"free-space floor in MB (default ${MIN_FREE_MB_ENV} or "
        f"{DEFAULT_MIN_FREE_MB}; 0 disables)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.version_file is None:
        args.version_file = str(Path(args.repo_dir) / "VERSION")
    if args.min_free_mb is None:
        args.min_free_mb = _min_free_mb_default()
    failures = run_checks(args)
    for reason in failures:
        print(f"PREFLIGHT FAIL: {reason}", file=sys.stderr)
    return EXIT_FAILED if failures else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
