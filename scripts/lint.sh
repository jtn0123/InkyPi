#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${SCRIPT_DIR}/.."
MYPY_SRC_BASELINE_FILE="${MYPY_SRC_BASELINE_FILE:-${REPO_ROOT}/scripts/mypy_src_baseline.txt}"
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

# Non-strict mypy is split into two passes (src/ and tests/) so that
# production-code type drift stays visible even when test-only typing
# noise dominates. src/ is ratcheted against a checked-in baseline;
# tests/ remains advisory. The strict subset below stays CI-blocking.
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

# Load the checked-in src/ advisory baseline used for the ratchet.
load_mypy_src_baseline() {
    local baseline_value

    if [ ! -f "$MYPY_SRC_BASELINE_FILE" ]; then
        echo "❌ mypy src/ ratchet baseline missing: $MYPY_SRC_BASELINE_FILE"
        return 1
    fi

    baseline_value="$(
        awk '
            /^[[:space:]]*#/ { next }
            /^[[:space:]]*$/ { next }
            { print $1; exit }
        ' "$MYPY_SRC_BASELINE_FILE"
    )"

    if [[ ! "$baseline_value" =~ ^[0-9]+$ ]]; then
        echo "❌ mypy src/ ratchet baseline is not a non-negative integer: $MYPY_SRC_BASELINE_FILE"
        return 1
    fi

    MYPY_SRC_BASELINE="$baseline_value"
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

    if [ "$MYPY_SRC_COUNT" -lt "$MYPY_SRC_BASELINE" ]; then
        echo "✅ mypy src/ ratchet improved: ${MYPY_SRC_COUNT} issue(s) vs baseline ${MYPY_SRC_BASELINE}"
        echo "ℹ️  Lower ${display_baseline_file} when that reduced count is ready to become the new floor."
        return
    fi

    echo "✅ mypy src/ ratchet held at baseline ${MYPY_SRC_BASELINE}"
}

run_counted_mypy src "src/" SRC ratchet
enforce_mypy_src_ratchet
run_counted_mypy tests "tests/" TESTS advisory

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
    src/utils/time_utils.py \
    src/utils/http_cache.py \
    src/model.py
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

# Report summary — src/ is ratcheted, tests/ stays advisory, and the strict
# subset remains fully blocking. Ruff, Black, and shellcheck are blocking too.
if [ $RUFF_EXIT -ne 0 ] || [ $BLACK_EXIT -ne 0 ] || [ $MYPY_SRC_RATCHET_EXIT -ne 0 ] || [ $MYPY_STRICT_EXIT -ne 0 ] || [ $SHELLCHECK_EXIT -ne 0 ]; then
    echo ""
    echo "❌ Some checks failed:"
    [ $RUFF_EXIT -ne 0 ] && echo "  - Ruff: $RUFF_EXIT"
    [ $BLACK_EXIT -ne 0 ] && echo "  - Black: $BLACK_EXIT"
    [ $MYPY_SRC_RATCHET_EXIT -ne 0 ] && echo "  - mypy src/ ratchet: $MYPY_SRC_RATCHET_EXIT"
    [ $MYPY_STRICT_EXIT -ne 0 ] && echo "  - mypy strict subset: $MYPY_STRICT_EXIT"
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
if [ $MYPY_TESTS_EXIT -ne 0 ]; then
    if [ "$MYPY_TESTS_COUNT" = "?" ]; then
        echo "⚠️  mypy tests/: failed without summary (non-blocking — see output above)"
    else
        echo "⚠️  mypy tests/: advisory only — ${MYPY_TESTS_COUNT} issue(s) remain (non-blocking)"
    fi
fi

if [ $RUFF_EXIT -ne 0 ] || [ $BLACK_EXIT -ne 0 ] || [ $MYPY_SRC_RATCHET_EXIT -ne 0 ] || [ $MYPY_STRICT_EXIT -ne 0 ] || [ $SHELLCHECK_EXIT -ne 0 ]; then
    exit 1
fi

exit 0
