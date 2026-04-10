#!/usr/bin/env bash
# precommit_browser_warning.sh — warn (not block) when frontend files are staged
# while SKIP_BROWSER=1 is set in the environment.
#
# Install via .pre-commit-config.yaml (see repo root) or run manually.
# This hook intentionally exits 0 so it never blocks a commit — it only prints
# a prominent warning reminding the contributor to run browser tests before
# opening a PR.

set -euo pipefail

# Only warn when SKIP_BROWSER is explicitly set to a truthy value
skip_browser="${SKIP_BROWSER:-0}"
case "$skip_browser" in
  1|true|yes) : ;;
  *) exit 0 ;;
esac

# Check whether any staged file is under src/static/ or src/templates/
if git diff --cached --name-only | grep -qE '^src/(static|templates)/'; then
  echo ""
  echo "┌──────────────────────────────────────────────────────────────────┐"
  echo "│  WARNING: SKIP_BROWSER=1 is set but you have frontend changes    │"
  echo "│  staged (src/static/** or src/templates/**).                     │"
  echo "│                                                                  │"
  echo "│  Browser tests MUST pass before opening a PR for these files.   │"
  echo "│  Run:                                                            │"
  echo "│    SKIP_BROWSER=0 .venv/bin/python -m pytest tests/             │"
  echo "│                                                                  │"
  echo "│  (This is a warning only — your commit is NOT blocked.)         │"
  echo "└──────────────────────────────────────────────────────────────────┘"
  echo ""
fi

exit 0
