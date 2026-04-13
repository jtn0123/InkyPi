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
MYPY_SRC_EXIT=0
MYPY_TESTS_EXIT=0
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

# Advisory mypy is split into two passes (src/ and tests/) so that
# production-code type drift stays visible even when test-only typing
# noise dominates. Both passes are non-blocking; only the strict subset
# below is CI-blocking. See docs/typing.md.
count_mypy_errors() {
    # Parse "Found N errors" / "Success: ..." lines from captured output.
    local output="$1"
    local n
    n=$(printf '%s\n' "$output" | grep -Eo 'Found [0-9]+ error' | grep -Eo '[0-9]+' | tail -1)
    if [ -z "$n" ]; then
        n=0
    fi
    echo "$n"
}

echo "Running mypy type checker (advisory — src/ only)..."
MYPY_SRC_OUTPUT="$(mypy src 2>&1)"
MYPY_SRC_EXIT=$?
echo "$MYPY_SRC_OUTPUT"
MYPY_SRC_COUNT=$(count_mypy_errors "$MYPY_SRC_OUTPUT")
if [ $MYPY_SRC_EXIT -ne 0 ]; then
    echo "⚠️  mypy src/: advisory only — ${MYPY_SRC_COUNT} issue(s) found"
else
    echo "✅ mypy src/ advisory type check passed"
fi

echo "Running mypy type checker (advisory — tests/ only)..."
MYPY_TESTS_OUTPUT="$(mypy tests 2>&1)"
MYPY_TESTS_EXIT=$?
echo "$MYPY_TESTS_OUTPUT"
MYPY_TESTS_COUNT=$(count_mypy_errors "$MYPY_TESTS_OUTPUT")
if [ $MYPY_TESTS_EXIT -ne 0 ]; then
    echo "⚠️  mypy tests/: advisory only — ${MYPY_TESTS_COUNT} issue(s) found"
else
    echo "✅ mypy tests/ advisory type check passed"
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
    src/refresh_task/actions.py \
    src/refresh_task/context.py \
    src/refresh_task/worker.py \
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
[ $MYPY_SRC_EXIT -ne 0 ] && echo "⚠️  mypy src/: advisory only — ${MYPY_SRC_COUNT} issue(s) remain (non-blocking)"
[ $MYPY_TESTS_EXIT -ne 0 ] && echo "⚠️  mypy tests/: advisory only — ${MYPY_TESTS_COUNT} issue(s) remain (non-blocking)"

if [ $RUFF_EXIT -ne 0 ] || [ $BLACK_EXIT -ne 0 ] || [ $MYPY_STRICT_EXIT -ne 0 ] || [ $SHELLCHECK_EXIT -ne 0 ]; then
    exit 1
fi

exit 0
