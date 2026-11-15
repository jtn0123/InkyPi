#!/usr/bin/env bash
# precommit_browser_warning.sh — run the browser smoke gate before pushing
# front-end changes.
#
# .pre-commit-config.yaml runs this at the pre-push stage, and only when the
# commits being pushed touch src/static/ or src/templates/ (the hook's
# `files` pattern). It can also be run by hand. A failing smoke suite blocks
# the push. Without Playwright Chromium the gate is skipped with a message:
# CI's browser-smoke job still runs it on every pull request.

set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

# The repo's .venv (or, in a git worktree, the main checkout's), as the other
# Python hooks use.
if ! scripts/precommit_tool.sh python - <<'PY' >/dev/null 2>&1
from playwright.sync_api import sync_playwright

with sync_playwright() as playwright:
    playwright.chromium.launch().close()
PY
then
  echo "Skipping the browser smoke gate: Playwright Chromium isn't available."
  echo "Install it with: python -m playwright install chromium"
  echo "(CI's browser-smoke job still runs the gate on every pull request.)"
  exit 0
fi

echo "Running the browser smoke gate for front-end changes..."
./scripts/test.sh browser-smoke
