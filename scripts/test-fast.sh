#!/usr/bin/env bash
# Fast local test loop (scripts/test.sh calls this for whole-suite runs).
#
# Runs the suite in parallel with pytest-xdist, then re-runs the memory-
# sensitive tests serially. Together the two passes select exactly what CI's
# tests job runs (`-m "not container"`); tests/unit/test_local_test_runner.py
# keeps it that way.
#
# The split exists because `-m memory` tests assert on this process's resident
# set size, which is only meaningful when it is not competing with sibling
# workers. Under load they fail on load, not on a real leak.
#
# Workers default to 4 (INKYPI_TEST_WORKERS overrides). `-n auto` started one
# worker per core, and that, or several suites at once, ran a Mac out
# of memory.
#
# CI stays serial on purpose (see .github/workflows/ci.yml — "Keep CI serial
# while the local pytest-xdist path soaks"), which is why this lives in a
# script rather than in pytest.ini addopts, where it would leak into CI.
#
# Usage:
#   scripts/test-fast.sh                 # whole suite, parallel
#   scripts/test-fast.sh tests/unit      # just one directory
#   scripts/test-fast.sh -k weather      # pass any pytest args through
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}/.." || exit 1

if [[ -z "${VIRTUAL_ENV:-}" && -f .venv/bin/activate ]]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi

# `container` tests boot systemd as PID 1 and are excluded from the normal run.
export SKIP_BROWSER="${SKIP_BROWSER:-1}"
export PYTHONPATH="src:.${PYTHONPATH:+:${PYTHONPATH}}"

TARGET=("${@:-tests/}")

# pytest exits 5 when a selection matches nothing, which is expected when the
# caller narrows to a single file that is entirely in (or out of) one pass.
run_pass() {
    local rc=0
    python -m pytest "$@" || rc=$?
    if [[ $rc -eq 5 ]]; then
        echo "    (no tests selected for this pass)"
        return 0
    fi
    return $rc
}

echo "==> parallel pass (excluding memory-sensitive tests)"
run_pass "${TARGET[@]}" -q -m "not container and not memory" \
    -n "${INKYPI_TEST_WORKERS:-4}" --dist=loadfile

echo "==> serial pass (memory-sensitive tests)"
run_pass "${TARGET[@]}" -q -m "not container and memory"
