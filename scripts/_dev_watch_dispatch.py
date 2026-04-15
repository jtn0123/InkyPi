#!/usr/bin/env python3
"""Dispatcher for scripts/dev_watch.sh.

Invoked by ``watchmedo shell-command`` on every matched filesystem event.
Responsibilities:

* Route the change to the right builder based on which watched dir the path
  lives under (styles → build_css.py, scripts → build_assets.py, templates →
  log-only since Flask auto-reloads templates).
* Debounce rapid successive events — IDE auto-save often fires a burst of
  create/modify/move events within a few ms. We coalesce anything within a
  200 ms window per (kind, builder) pair using an on-disk timestamp so that
  successive ``watchmedo`` invocations (each a fresh subprocess) can see the
  previous one's activity.
* Print exactly one line per rebuild:
    ``[2026-04-14T12:34:56] rebuild css (source: _buttons.css)``
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STYLES_DIR = REPO_ROOT / "src" / "static" / "styles"
SCRIPTS_DIR = REPO_ROOT / "src" / "static" / "scripts"
TEMPLATES_DIR = REPO_ROOT / "src" / "templates"

# 200 ms debounce window — coalesces IDE save bursts without feeling laggy.
DEBOUNCE_SECONDS = 0.2

# Where we stash per-kind "last build" timestamps. Using the system tempdir
# keeps the repo clean and avoids confusing git status.
_STATE_DIR = Path(tempfile.gettempdir()) / "inkypi-dev-watch"


def _kind_for(path: Path) -> str | None:
    """Return 'css', 'js', 'template', or None if the path isn't watched."""
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path

    for candidate, label in (
        (STYLES_DIR, "css"),
        (SCRIPTS_DIR, "js"),
        (TEMPLATES_DIR, "template"),
    ):
        try:
            resolved.relative_to(candidate.resolve())
            return label
        except ValueError:
            continue
    return None


def _debounce(kind: str) -> bool:
    """Return True if we should proceed; False if another event just ran.

    State is tracked per-kind in a temp file so the debounce survives across
    the short-lived subprocesses that ``watchmedo shell-command`` spawns.
    """
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = _STATE_DIR / f"{kind}.last"
    now = time.monotonic()
    try:
        last = float(stamp.read_text().strip())
    except (FileNotFoundError, ValueError):
        last = 0.0
    if now - last < DEBOUNCE_SECONDS:
        return False
    stamp.write_text(str(now))
    return True


def _log(action: str, source: Path) -> None:
    # Local wall-clock time, stripped to seconds. Developers read this at
    # the terminal — an ISO-with-offset string would be harder to scan.
    ts = datetime.now().astimezone().replace(microsecond=0, tzinfo=None).isoformat()
    print(f"[{ts}] {action} (source: {source.name})", flush=True)


def _run_builder(script: str) -> int:
    """Run scripts/<script> with the current Python, return exit code."""
    builder = REPO_ROOT / "scripts" / script
    result = subprocess.run(
        [sys.executable, str(builder)],
        cwd=str(REPO_ROOT),
        check=False,
    )
    return result.returncode


def main(argv: list[str]) -> int:
    # watchmedo passes: <event_type> <src_path>
    if len(argv) < 3:
        return 0
    event_type = argv[1]
    src_path = Path(argv[2])

    # Ignore directory-level events; --ignore-directories in the shell command
    # should prevent these, but be defensive.
    if event_type == "moved" and src_path.is_dir():
        return 0

    kind = _kind_for(src_path)
    if kind is None:
        return 0

    if not _debounce(kind):
        return 0

    if kind == "css":
        _log("rebuild css", src_path)
        return _run_builder("build_css.py")
    if kind == "js":
        _log("rebuild js", src_path)
        # build_assets.py covers both JS and CSS; we run it here to refresh
        # the dist/ bundle hash used by base.html.
        return _run_builder("build_assets.py")
    if kind == "template":
        # Flask's reloader picks up template changes; no build step needed.
        _log("template changed (Flask will auto-reload)", src_path)
        return 0
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except KeyboardInterrupt:  # pragma: no cover - interactive only
        sys.exit(0)
    except OSError as exc:  # pragma: no cover - defensive
        print(f"dev_watch dispatch error: {exc}", file=sys.stderr)
        sys.exit(1)
