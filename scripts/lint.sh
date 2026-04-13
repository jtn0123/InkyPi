#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${SCRIPT_DIR}/.."
cd "${REPO_ROOT}" || exit

# Use existing environment in CI or when a virtualenv is active
if [[ -z "${CI:-}" && -z "${VIRTUAL_ENV:-}" ]]; then
    # shellcheck source=scripts/venv.sh
    source scripts/venv.sh
fi

# Track failures
RUFF_EXIT=0
BLACK_EXIT=0
MYPY_EXIT=0
MYPY_STRICT_EXIT=0
SHELLCHECK_EXIT=0

echo "Running Ruff linter..."
ruff check src tests scripts
RUFF_EXIT=$?
if [ $RUFF_EXIT -ne 0 ]; then
    echo "❌ Ruff found issues (exit code: $RUFF_EXIT)"
else
    echo "✅ Ruff passed"
fi

echo "Running Black format check..."
black --check src tests scripts
BLACK_EXIT=$?
if [ $BLACK_EXIT -ne 0 ]; then
    echo "❌ Black found formatting issues (exit code: $BLACK_EXIT)"
else
    echo "✅ Black formatting check passed"
fi

echo "Running mypy type checker (advisory — whole codebase)..."
mypy src tests
MYPY_EXIT=$?
if [ $MYPY_EXIT -ne 0 ]; then
    echo "⚠️  mypy: advisory only (except strict subset) — $MYPY_EXIT issue(s) found"
else
    echo "✅ mypy advisory type check passed"
fi

echo "Running mypy strict check (blocking — strict subset only)..."
# Strict subset: curated low-churn helpers that are enforced at --strict.
# See docs/typing.md for how to add more modules to this list.
mypy --strict \
    src/utils/http_utils.py \
    src/utils/security_utils.py \
    src/utils/client_endpoint.py \
    src/utils/display_names.py \
    src/utils/messages.py \
    src/utils/output_validator.py \
    src/utils/paths.py \
    src/utils/refresh_info.py \
    src/utils/refresh_stats.py \
    src/utils/sri.py \
    src/utils/time_utils.py
MYPY_STRICT_EXIT=$?
if [ $MYPY_STRICT_EXIT -ne 0 ]; then
    echo "❌ mypy strict helper subset failed (exit code: $MYPY_STRICT_EXIT)"
else
    echo "✅ mypy strict helper subset clean"
fi

# Shell scripts under install/ and scripts/ — must pass shellcheck.
# Dynamic discovery ensures new scripts are covered automatically.
shopt -s nullglob
EXISTING_SHELLCHECK_FILES=(install/*.sh scripts/*.sh)
shopt -u nullglob

echo "Running shellcheck..."
if command -v shellcheck > /dev/null 2>&1; then
    if [[ ${#EXISTING_SHELLCHECK_FILES[@]} -gt 0 ]]; then
        shellcheck --severity=warning "${EXISTING_SHELLCHECK_FILES[@]}"
        SHELLCHECK_EXIT=$?
    else
        echo "No shell script files found to check."
    fi
    if [ $SHELLCHECK_EXIT -ne 0 ]; then
        echo "❌ shellcheck found issues (exit code: $SHELLCHECK_EXIT)"
    else
        echo "✅ shellcheck passed"
    fi
else
    # In CI the binary must be present; locally we skip with a warning.
    if [[ -n "${CI:-}" ]]; then
        echo "❌ shellcheck not found — install it in the CI image."
        SHELLCHECK_EXIT=1
    else
        echo "⚠️  shellcheck not found — skipping (install via: brew install shellcheck / apt install shellcheck)"
    fi
fi

# Report summary — whole-codebase mypy is advisory only; the strict subset
# (typed helper subset) is blocking. Ruff, Black, and shellcheck are blocking.
if [ $RUFF_EXIT -ne 0 ] || [ $BLACK_EXIT -ne 0 ] || [ $MYPY_STRICT_EXIT -ne 0 ] || [ $SHELLCHECK_EXIT -ne 0 ]; then
    echo ""
    echo "❌ Some checks failed:"
    [ $RUFF_EXIT -ne 0 ] && echo "  - Ruff: $RUFF_EXIT"
    [ $BLACK_EXIT -ne 0 ] && echo "  - Black: $BLACK_EXIT"
    [ $MYPY_STRICT_EXIT -ne 0 ] && echo "  - mypy strict subset: $MYPY_STRICT_EXIT"
    [ $SHELLCHECK_EXIT -ne 0 ] && echo "  - shellcheck: $SHELLCHECK_EXIT"
    echo ""
    echo "Post-run actions will continue..."
else
    echo ""
    echo "✅ All checks passed!"
fi
[ $MYPY_EXIT -ne 0 ] && echo "⚠️  mypy: advisory only (except strict subset) — issues remain (non-blocking)"

if [ $RUFF_EXIT -ne 0 ] || [ $BLACK_EXIT -ne 0 ] || [ $MYPY_STRICT_EXIT -ne 0 ] || [ $SHELLCHECK_EXIT -ne 0 ]; then
    exit 1
fi

exit 0
