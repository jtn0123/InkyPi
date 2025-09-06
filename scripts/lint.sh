#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${SCRIPT_DIR}/.."
cd "${REPO_ROOT}"

source scripts/venv.sh

# Track failures
RUFF_EXIT=0
BLACK_EXIT=0
MYPY_EXIT=0

echo "Running Ruff linter..."
if ! ruff check src tests scripts; then
    RUFF_EXIT=$?
    echo "❌ Ruff found issues (exit code: $RUFF_EXIT)"
else
    echo "✅ Ruff passed"
fi

echo "Running Black format check..."
if ! black --check src tests scripts; then
    BLACK_EXIT=$?
    echo "❌ Black found formatting issues (exit code: $BLACK_EXIT)"
else
    echo "✅ Black formatting check passed"
fi

echo "Running mypy type checker..."
if ! mypy src tests; then
    MYPY_EXIT=$?
    echo "❌ mypy found type issues (exit code: $MYPY_EXIT)"
else
    echo "✅ mypy type check passed"
fi

# Report summary
if [ $RUFF_EXIT -ne 0 ] || [ $BLACK_EXIT -ne 0 ] || [ $MYPY_EXIT -ne 0 ]; then
    echo ""
    echo "❌ Some checks failed:"
    [ $RUFF_EXIT -ne 0 ] && echo "  - Ruff: $RUFF_EXIT"
    [ $BLACK_EXIT -ne 0 ] && echo "  - Black: $BLACK_EXIT"
    [ $MYPY_EXIT -ne 0 ] && echo "  - mypy: $MYPY_EXIT"
    echo ""
    echo "Post-run actions will continue..."
else
    echo ""
    echo "✅ All checks passed!"
fi


