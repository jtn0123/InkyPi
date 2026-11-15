#!/usr/bin/env bash
# Local test entry point.
#
#   scripts/test.sh                          # whole suite, same selection as CI
#   scripts/test.sh tests/unit/test_x.py -v  # one file: serial
#   scripts/test.sh tests/unit -k weather    # anything else: scripts/test-fast.sh
#   scripts/test.sh browser-smoke            # browser smoke (needs Chromium)
#
# The whole-suite and multi-target runs go through scripts/test-fast.sh: one
# pytest run with at most INKYPI_TEST_WORKERS (default 4) xdist workers, then
# a serial pass for the memory-sensitive tests. This used to start four
# lanes of two workers each, which ran a Mac out of memory, and the
# lanes left out about 50 test files that CI runs.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${SCRIPT_DIR}/.."
cd "${REPO_ROOT}" || exit

# Use the active virtualenv when provided. Otherwise activate an existing repo
# venv directly so test runs do not reinstall dependencies on each invocation.
if [[ -z "${VIRTUAL_ENV:-}" ]]; then
    if [[ -f ".venv/bin/activate" ]]; then
        # shellcheck source=/dev/null
        source ".venv/bin/activate"
    else
        # shellcheck source=scripts/venv.sh
        source scripts/venv.sh
    fi
fi

python scripts/dev_environment.py

export PYTHONPATH="src${PYTHONPATH:+:$PYTHONPATH}"

if [[ "${1:-}" == "browser-smoke" ]]; then
    shift || true
    REQUIRE_BROWSER_SMOKE=1 python -m pytest -q tests/integration/test_browser_smoke.py "$@"
    exit $?
fi

target_count=0
file_target_count=0
for arg in "$@"; do
    [[ "$arg" == -* ]] && continue
    target="${arg%%::*}"
    [[ -e "$target" ]] || continue
    ((target_count += 1))
    if [[ -f "$target" ]]; then
        ((file_target_count += 1))
    fi
done

if [[ "${target_count}" -eq 1 && "${file_target_count}" -eq 1 ]]; then
    # One file: run it serially. tests/conftest.py decides whether a browser
    # file runs (Chromium installed) or skips.
    exec python -m pytest -q "$@"
fi

exec "${SCRIPT_DIR}/test-fast.sh" "$@"
