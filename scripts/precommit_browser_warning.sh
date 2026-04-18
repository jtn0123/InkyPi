#!/usr/bin/env bash
# precommit_browser_warning.sh — run the browser smoke gate when frontend files
# are staged.
#
# Install via .pre-commit-config.yaml (see repo root) or run manually.
# This hook exits non-zero when the smoke suite fails so frontend changes
# cannot be committed without the lightweight browser gate passing first.

set -euo pipefail

# Check whether any staged file is under src/static/ or src/templates/
if ! git diff --cached --name-only | grep -qE '^src/(static|templates)/'; then
  exit 0
fi

echo "Running browser smoke gate for staged frontend changes..."
./scripts/test.sh browser-smoke

exit 0
