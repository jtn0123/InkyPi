#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${SCRIPT_DIR}/.."
MYPY_SRC_BASELINE_FILE="${MYPY_SRC_BASELINE_FILE:-${REPO_ROOT}/scripts/mypy_src_baseline.txt}"
MYPY_TESTS_BASELINE_FILE="${MYPY_TESTS_BASELINE_FILE:-${REPO_ROOT}/scripts/mypy_tests_baseline.txt}"
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
MYPY_SRC_BASELINE="?"
MYPY_SRC_RATCHET_EXIT=0
MYPY_TESTS_EXIT=0
MYPY_TESTS_BASELINE="?"
MYPY_TESTS_RATCHET_EXIT=0
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

# mypy runs in strict mode (mypy.ini) as two passes, src/ and tests/, so that
# production-code type drift stays visible even when test-only typing noise
# dominates. src/ must stay clean, while tests/ is ratcheted against a
# checked-in baseline so new test typing debt cannot slip in silently.
# See docs/typing.md.
count_mypy_errors() {
    # Parse "Found N errors" / "Success: ..." lines from captured output.
    # Returns "?" when mypy exited non-zero without a recognizable summary
    # (config error, import failure, crash) so callers don't misreport "0".
    local output="$1"
    local exit_code="${2:-0}"
    local n
    n=$(printf '%s\n' "$output" | sed -nE 's/.*Found ([0-9]+) errors?.*/\1/p' | tail -1)
    if [ -z "$n" ]; then
        if printf '%s\n' "$output" | grep -q '^Success:'; then
            n=0
        elif [ "$exit_code" -ne 0 ]; then
            # Non-zero exit, no summary — treat as a failed run with unknown count
            n="?"
        else
            n=0
        fi
    fi
    echo "$n"
}

load_mypy_baseline() {
    local baseline_file="$1"
    local label="$2"
    local baseline_value

    if [ ! -f "$baseline_file" ]; then
        echo "❌ mypy ${label} ratchet baseline missing: $baseline_file" >&2
        return 1
    fi

    # Exactly one value line is allowed. With two, an edit to the wrong one
    # silently does nothing, which is how this file once kept a stale floor.
    local value_lines
    value_lines="$(grep -cvE '^[[:space:]]*(#|$)' "$baseline_file" || true)"
    if [ "$value_lines" != "1" ]; then
        echo "❌ mypy ${label} ratchet baseline must hold exactly one value line, found ${value_lines}: $baseline_file" >&2
        return 1
    fi

    baseline_value="$(grep -vE '^[[:space:]]*(#|$)' "$baseline_file" | awk '{ print $1 }')"

    if [[ ! "$baseline_value" =~ ^[0-9]+$ ]]; then
        echo "❌ mypy ${label} ratchet baseline is not a non-negative integer: $baseline_file" >&2
        return 1
    fi

    echo "$baseline_value"
}

# Load the checked-in src/ baseline. This should remain zero now that
# production-code mypy debt has been cleared.
load_mypy_src_baseline() {
    local baseline_value

    baseline_value="$(load_mypy_baseline "$MYPY_SRC_BASELINE_FILE" "src/")" || return 1
    MYPY_SRC_BASELINE="$baseline_value"
}

load_mypy_tests_baseline() {
    local baseline_value

    baseline_value="$(load_mypy_baseline "$MYPY_TESTS_BASELINE_FILE" "tests/")" || return 1
    MYPY_TESTS_BASELINE="$baseline_value"
}

# Run mypy on a directory and capture its error count for either advisory
# reporting or ratchet comparison.
# Sets globals MYPY_<UPPER_LABEL>_EXIT and MYPY_<UPPER_LABEL>_COUNT so the
# outer script can reference them in the summary block below.
run_counted_mypy() {
    local dir_path="$1"
    local label="$2"
    local var_key="$3"   # e.g. SRC or TESTS — used to build global var names
    local mode="$4"      # ratchet or advisory
    local output
    local exit_code
    local count

    echo "Running mypy type checker (${mode} — ${label} only)..."
    output="$(mypy "$dir_path" 2>&1)"
    exit_code=$?
    echo "$output"
    count=$(count_mypy_errors "$output" "$exit_code")

    if [ "$exit_code" -ne 0 ]; then
        if [ "$count" = "?" ]; then
            echo "⚠️  mypy ${label}: failed (see output above)"
        elif [ "$mode" = "ratchet" ]; then
            echo "ℹ️  mypy ${label}: ${count} issue(s) found; comparing against ratchet baseline"
        else
            echo "⚠️  mypy ${label}: advisory only — ${count} issue(s) found"
        fi
    else
        echo "✅ mypy ${label} type check passed"
    fi

    # Write through to globals for the final summary.
    printf -v "MYPY_${var_key}_EXIT" '%s' "$exit_code"
    printf -v "MYPY_${var_key}_COUNT" '%s' "$count"
}

enforce_mypy_src_ratchet() {
    local display_baseline_file="${MYPY_SRC_BASELINE_FILE#"${REPO_ROOT}"/}"

    if ! load_mypy_src_baseline; then
        MYPY_SRC_RATCHET_EXIT=1
        return
    fi

    if [ "$MYPY_SRC_COUNT" = "?" ]; then
        echo "❌ mypy src/ ratchet failed: unable to determine the advisory count for comparison"
        MYPY_SRC_RATCHET_EXIT=1
        return
    fi

    if [ "$MYPY_SRC_COUNT" -gt "$MYPY_SRC_BASELINE" ]; then
        echo "❌ mypy src/ ratchet failed: ${MYPY_SRC_COUNT} issue(s) exceeds baseline ${MYPY_SRC_BASELINE}"
        MYPY_SRC_RATCHET_EXIT=1
        return
    fi

    if [ "$MYPY_SRC_BASELINE" -eq 0 ] && [ "$MYPY_SRC_EXIT" -ne 0 ]; then
        echo "❌ mypy src/ must remain clean now that the baseline is zero"
        MYPY_SRC_RATCHET_EXIT=1
        return
    fi

    if [ "$MYPY_SRC_COUNT" -lt "$MYPY_SRC_BASELINE" ]; then
        echo "✅ mypy src/ ratchet improved: ${MYPY_SRC_COUNT} issue(s) vs baseline ${MYPY_SRC_BASELINE}"
        echo "ℹ️  Lower ${display_baseline_file} when that reduced count is ready to become the new floor."
        return
    fi

    if [ "$MYPY_SRC_BASELINE" -eq 0 ]; then
        echo "✅ mypy src/ remains clean"
    else
        echo "✅ mypy src/ ratchet held at baseline ${MYPY_SRC_BASELINE}"
    fi
}

enforce_mypy_tests_ratchet() {
    local display_baseline_file="${MYPY_TESTS_BASELINE_FILE#"${REPO_ROOT}"/}"

    if ! load_mypy_tests_baseline; then
        MYPY_TESTS_RATCHET_EXIT=1
        return
    fi

    if [ "$MYPY_TESTS_COUNT" = "?" ]; then
        echo "❌ mypy tests/ ratchet failed: unable to determine the advisory count for comparison"
        MYPY_TESTS_RATCHET_EXIT=1
        return
    fi

    if [ "$MYPY_TESTS_COUNT" -gt "$MYPY_TESTS_BASELINE" ]; then
        echo "❌ mypy tests/ ratchet failed: ${MYPY_TESTS_COUNT} issue(s) exceeds baseline ${MYPY_TESTS_BASELINE}"
        MYPY_TESTS_RATCHET_EXIT=1
        return
    fi

    if [ "$MYPY_TESTS_BASELINE" -eq 0 ] && [ "$MYPY_TESTS_EXIT" -ne 0 ]; then
        echo "❌ mypy tests/ must remain clean now that the baseline is zero"
        MYPY_TESTS_RATCHET_EXIT=1
        return
    fi

    if [ "$MYPY_TESTS_COUNT" -lt "$MYPY_TESTS_BASELINE" ]; then
        echo "✅ mypy tests/ ratchet improved: ${MYPY_TESTS_COUNT} issue(s) vs baseline ${MYPY_TESTS_BASELINE}"
        echo "ℹ️  Lower ${display_baseline_file} when that reduced count is ready to become the new floor."
        return
    fi

    echo "✅ mypy tests/ ratchet held at baseline ${MYPY_TESTS_BASELINE}"
}

run_counted_mypy src "src/" SRC ratchet
enforce_mypy_src_ratchet
run_counted_mypy tests "tests/" TESTS ratchet
enforce_mypy_tests_ratchet

# Every tracked shell script: bash -n, then shellcheck at its default
# severity. This is the only shellcheck run; CI's lint job gets it from here.
# check_shell.sh discovers the scripts, so new ones are covered automatically.
echo "Running shell script checks..."
scripts/check_shell.sh
SHELLCHECK_EXIT=$?

# Report summary — src/ must stay clean and tests/ is ratcheted. Ruff, Black,
# and shellcheck are blocking too.
if [ $RUFF_EXIT -ne 0 ] || [ $BLACK_EXIT -ne 0 ] || [ $MYPY_SRC_RATCHET_EXIT -ne 0 ] || [ $MYPY_TESTS_RATCHET_EXIT -ne 0 ] || [ $SHELLCHECK_EXIT -ne 0 ]; then
    echo ""
    echo "❌ Some checks failed:"
    [ $RUFF_EXIT -ne 0 ] && echo "  - Ruff: $RUFF_EXIT"
    [ $BLACK_EXIT -ne 0 ] && echo "  - Black: $BLACK_EXIT"
    [ $MYPY_SRC_RATCHET_EXIT -ne 0 ] && echo "  - mypy src/ ratchet: $MYPY_SRC_RATCHET_EXIT"
    [ $MYPY_TESTS_RATCHET_EXIT -ne 0 ] && echo "  - mypy tests/ ratchet: $MYPY_TESTS_RATCHET_EXIT"
    [ $SHELLCHECK_EXIT -ne 0 ] && echo "  - shellcheck: $SHELLCHECK_EXIT"
    echo ""
    echo "Post-run actions will continue..."
else
    echo ""
    echo "✅ All checks passed!"
fi
if [ "$MYPY_SRC_BASELINE" = "?" ]; then
    echo "❌ mypy src/: ratchet baseline could not be loaded"
elif [ "$MYPY_SRC_COUNT" = "?" ]; then
    echo "❌ mypy src/: ratchet could not compare against baseline ${MYPY_SRC_BASELINE}"
elif [ "$MYPY_SRC_COUNT" -gt "$MYPY_SRC_BASELINE" ]; then
    echo "❌ mypy src/: ${MYPY_SRC_COUNT} issue(s) exceeds baseline ${MYPY_SRC_BASELINE}"
elif [ "$MYPY_SRC_COUNT" -lt "$MYPY_SRC_BASELINE" ]; then
    echo "✅ mypy src/: ${MYPY_SRC_COUNT} issue(s) (below baseline ${MYPY_SRC_BASELINE})"
elif [ $MYPY_SRC_EXIT -eq 0 ]; then
    echo "✅ mypy src/: clean"
else
    echo "✅ mypy src/: ${MYPY_SRC_COUNT} issue(s) matches baseline ${MYPY_SRC_BASELINE}"
fi
if [ "$MYPY_TESTS_BASELINE" = "?" ]; then
    echo "❌ mypy tests/: ratchet baseline could not be loaded"
elif [ "$MYPY_TESTS_COUNT" = "?" ]; then
    echo "❌ mypy tests/: ratchet could not compare against baseline ${MYPY_TESTS_BASELINE}"
elif [ "$MYPY_TESTS_COUNT" -gt "$MYPY_TESTS_BASELINE" ]; then
    echo "❌ mypy tests/: ${MYPY_TESTS_COUNT} issue(s) exceeds baseline ${MYPY_TESTS_BASELINE}"
elif [ "$MYPY_TESTS_COUNT" -lt "$MYPY_TESTS_BASELINE" ]; then
    echo "✅ mypy tests/: ${MYPY_TESTS_COUNT} issue(s) (below baseline ${MYPY_TESTS_BASELINE})"
elif [ $MYPY_TESTS_EXIT -eq 0 ]; then
    echo "✅ mypy tests/: clean"
else
    echo "✅ mypy tests/: ${MYPY_TESTS_COUNT} issue(s) matches baseline ${MYPY_TESTS_BASELINE}"
fi

if [ $RUFF_EXIT -ne 0 ] || [ $BLACK_EXIT -ne 0 ] || [ $MYPY_SRC_RATCHET_EXIT -ne 0 ] || [ $MYPY_TESTS_RATCHET_EXIT -ne 0 ] || [ $SHELLCHECK_EXIT -ne 0 ]; then
    exit 1
fi

exit 0
