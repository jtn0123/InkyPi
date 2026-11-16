#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${SCRIPT_DIR}/.."
MYPY_SRC_BASELINE_FILE="${MYPY_SRC_BASELINE_FILE:-${REPO_ROOT}/scripts/mypy_src_baseline.txt}"
MYPY_TESTS_BASELINE_FILE="${MYPY_TESTS_BASELINE_FILE:-${REPO_ROOT}/scripts/mypy_tests_baseline.txt}"
MYPY_SCRIPTS_BASELINE_FILE="${MYPY_SCRIPTS_BASELINE_FILE:-${REPO_ROOT}/scripts/mypy_scripts_baseline.txt}"
cd "${REPO_ROOT}" || exit

# Use existing environment in CI or when a virtualenv is active
if [[ -z "${CI:-}" && -z "${VIRTUAL_ENV:-}" ]]; then
    # shellcheck source=scripts/venv.sh
    source scripts/venv.sh
fi

# Track failures
RUFF_EXIT=0
BLACK_EXIT=0
MYPY_FAILED=""
SHELLCHECK_EXIT=0
BIOME_EXIT=0

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

# mypy runs in strict mode (mypy.ini) as three passes, src/, tests/ and
# scripts/, so production-code type drift stays visible even when test-only
# typing noise dominates. Each pass is compared with its checked-in baseline,
# a list of `path:error-code` fingerprints with their error counts:
# scripts/mypy_ratchet.py fails on any fingerprint that is new, has gone, or
# has a different count, and prints only those. The src/ and scripts/
# baselines are empty, so any error there fails. See docs/typing.md.
run_mypy_ratchet() {
    local dir="$1" baseline="$2"
    echo "Running mypy type checker (strict, ${dir}/) against ${baseline#"${REPO_ROOT}"/}..."
    if ! python scripts/mypy_ratchet.py "$dir" "$baseline"; then
        MYPY_FAILED="${MYPY_FAILED:+$MYPY_FAILED }${dir}/"
    fi
}

run_mypy_ratchet src "$MYPY_SRC_BASELINE_FILE"
run_mypy_ratchet tests "$MYPY_TESTS_BASELINE_FILE"
run_mypy_ratchet scripts "$MYPY_SCRIPTS_BASELINE_FILE"

# Every tracked shell script: bash -n, then shellcheck at its default
# severity. This is the only shellcheck run; CI's lint job gets it from here.
# check_shell.sh discovers the scripts, so new ones are covered automatically.
echo "Running shell script checks..."
scripts/check_shell.sh
SHELLCHECK_EXIT=$?

# Biome lints the web scripts and the service worker (biome.json), as CI's
# lint job does in its own step, so a green local run means a green CI lint.
# Locally, prefer the pinned version through the biome-ci pre-commit hook.
if [[ -n "${CI:-}" ]]; then
    echo "Skipping Biome here: CI's lint job runs it in its own step"
elif command -v pre-commit >/dev/null 2>&1; then
    echo "Running Biome (pinned, via the biome-ci pre-commit hook)..."
    pre-commit run biome-ci --all-files
    BIOME_EXIT=$?
elif command -v biome >/dev/null 2>&1; then
    echo "Running Biome..."
    biome ci --error-on-warnings
    BIOME_EXIT=$?
else
    echo "⚠️  Biome not run: install the dev requirements (they include pre-commit)"
fi
if [ $BIOME_EXIT -ne 0 ]; then
    echo "❌ Biome found issues (exit code: $BIOME_EXIT)"
fi

# Report summary. Ruff, Black, every mypy ratchet, shellcheck and Biome are
# blocking.
if [ $RUFF_EXIT -ne 0 ] || [ $BLACK_EXIT -ne 0 ] || [ -n "$MYPY_FAILED" ] || [ $SHELLCHECK_EXIT -ne 0 ] || [ $BIOME_EXIT -ne 0 ]; then
    echo ""
    echo "❌ Some checks failed:"
    [ $RUFF_EXIT -ne 0 ] && echo "  - Ruff: $RUFF_EXIT"
    [ $BLACK_EXIT -ne 0 ] && echo "  - Black: $BLACK_EXIT"
    [ -n "$MYPY_FAILED" ] && echo "  - mypy ratchet: $MYPY_FAILED (differences printed above)"
    [ $SHELLCHECK_EXIT -ne 0 ] && echo "  - shellcheck: $SHELLCHECK_EXIT"
    [ $BIOME_EXIT -ne 0 ] && echo "  - Biome: $BIOME_EXIT"
    exit 1
fi

echo ""
echo "✅ All checks passed!"
exit 0
