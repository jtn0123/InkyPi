#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${SCRIPT_DIR}/.."
cd "${REPO_ROOT}" || exit

source scripts/venv.sh

# Track failures
RUFF_EXIT=0
BLACK_EXIT=0

echo "Running Ruff auto-fix..."
if ! ruff check --fix src tests scripts; then
    RUFF_EXIT=$?
    echo "❌ Ruff auto-fix completed with issues (exit code: $RUFF_EXIT)"
else
    echo "✅ Ruff auto-fix completed"
fi

echo "Running Black formatting..."
if ! black src tests scripts; then
    BLACK_EXIT=$?
    echo "❌ Black formatting completed with issues (exit code: $BLACK_EXIT)"
else
    echo "✅ Black formatting completed"
fi

# Report summary
if [ $RUFF_EXIT -ne 0 ] || [ $BLACK_EXIT -ne 0 ]; then
    echo ""
    echo "❌ Some formatting tools had issues:"
    [ $RUFF_EXIT -ne 0 ] && echo "  - Ruff: $RUFF_EXIT"
    [ $BLACK_EXIT -ne 0 ] && echo "  - Black: $BLACK_EXIT"
    echo ""
    echo "Post-run actions will continue..."
else
    echo ""
    echo "✅ All formatting completed successfully!"
fi


