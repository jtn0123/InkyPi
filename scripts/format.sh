#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${SCRIPT_DIR}/.."
cd "${REPO_ROOT}" || exit

# Use the active virtualenv when there is one (as lint.sh does), so a caller
# can choose the tools on PATH.
if [[ -z "${VIRTUAL_ENV:-}" ]]; then
    # shellcheck source=scripts/venv.sh
    source scripts/venv.sh
fi

# Track failures. `cmd || X=$?` keeps the tool's own exit status; inside
# `if ! cmd; then X=$?`, $? is the status of the `!`, which is always 0.
RUFF_EXIT=0
BLACK_EXIT=0

echo "Running Ruff auto-fix..."
ruff check --fix src tests scripts || RUFF_EXIT=$?
if [ "$RUFF_EXIT" -ne 0 ]; then
    echo "❌ Ruff auto-fix completed with issues (exit code: $RUFF_EXIT)"
else
    echo "✅ Ruff auto-fix completed"
fi

echo "Running Black formatting..."
black src tests scripts || BLACK_EXIT=$?
if [ "$BLACK_EXIT" -ne 0 ]; then
    echo "❌ Black formatting completed with issues (exit code: $BLACK_EXIT)"
else
    echo "✅ Black formatting completed"
fi

# Report summary
if [ "$RUFF_EXIT" -ne 0 ] || [ "$BLACK_EXIT" -ne 0 ]; then
    echo ""
    echo "❌ Some formatting tools had issues:"
    [ "$RUFF_EXIT" -ne 0 ] && echo "  - Ruff: $RUFF_EXIT"
    [ "$BLACK_EXIT" -ne 0 ] && echo "  - Black: $BLACK_EXIT"
    exit 1
fi

echo ""
echo "✅ All formatting completed successfully!"
