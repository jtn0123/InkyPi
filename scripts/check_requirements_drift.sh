#!/usr/bin/env bash
# check_requirements_drift.sh — verify uv-exported lockfile is in sync.
#
# JTN-616: migrated from pip-compile to `uv lock` + `uv export`. The universal
# lockfile produced by uv resolves all supported platforms in a single file,
# which eliminates the previous pain points around:
#   - Python version mismatches (the project targets 3.13 only)
#   - sys_platform-gated packages (cysystemd, gpiod)
#   - Multi-arch wheel hash coverage (arm64/armv7l/aarch64)
#
# Source of truth: pyproject.toml + uv.lock.
# install/requirements.txt is regenerated from uv.lock via `uv export`.
#
# This script:
#   1. Ensures uv.lock is up to date with pyproject.toml (`uv lock --check`).
#   2. Exports install/requirements.txt and install/requirements-dev.txt into
#      temp files with scripts/export_requirements.sh and diffs them against
#      the committed copies.
#   3. Checks the installer requirement files against their .in files and
#      against uv.lock.
#
# Usage:
#   scripts/check_requirements_drift.sh
#
# Exits 0 when in sync, 1 when drift is detected.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "${REPO_ROOT}"

if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: uv is not installed. Install with:  pip install uv" >&2
    exit 1
fi

DRIFT_FOUND=0

echo "==> Checking uv.lock is in sync with pyproject.toml ..."
if ! uv lock --check >/dev/null 2>&1; then
    echo "ERROR: uv.lock is out of sync with pyproject.toml."
    echo "Run:  uv lock"
    DRIFT_FOUND=1
else
    echo "    OK — uv.lock is up to date."
fi

echo "==> Checking install/requirements.txt and install/requirements-dev.txt match uv export ..."
tmp_export="$(mktemp /tmp/requirements-check-XXXXXX.txt)"
tmp_dev="$(mktemp /tmp/requirements-dev-check-XXXXXX.txt)"
trap 'rm -f "${tmp_export}" "${tmp_dev}"' EXIT

# The same script regenerates the committed files (and the Dependabot exports
# workflow runs it on every uv.lock bump), so this compares like with like.
bash scripts/export_requirements.sh "${tmp_export}" "${tmp_dev}"

for pair in "install/requirements.txt|${tmp_export}" "install/requirements-dev.txt|${tmp_dev}"; do
    committed="${pair%%|*}"
    if diff -u "${committed}" "${pair#*|}"; then
        echo "    OK — ${committed} is up to date."
    else
        echo ""
        echo "ERROR: ${committed} is out of sync with uv.lock."
        echo "Regenerate both exports and commit the result:"
        echo ""
        echo "  bash scripts/export_requirements.sh"
        echo ""
        DRIFT_FOUND=1
    fi
done

# Installer tools and optional hardware dependencies use the same integrity
# contract as runtime dependencies. Resolve against committed versions.
for lock_name in bootstrap uv ws; do
    lock_txt="install/${lock_name}-requirements.txt"
    if ! uv --no-config pip compile \
        --universal --python-version 3.13 --prerelease disallow \
        --generate-hashes --constraints "$lock_txt" --no-header --no-annotate \
        "install/${lock_name}-requirements.in" --output-file "$tmp_dev" --quiet; then
        echo "ERROR: ${lock_name} installer requirements do not resolve."
        DRIFT_FOUND=1
    elif ! diff -u "$lock_txt" "$tmp_dev"; then
        echo "ERROR: regenerate ${lock_txt} with universal hash generation."
        DRIFT_FOUND=1
    fi
done

echo "==> Checking installer requirement files agree with uv.lock ..."
# Those files aren't exported from the lock, so a Dependabot bump never
# touches them; a package pinned in both must match the lock's version and
# hashes, and one pinned in two of them must match itself.
if ! python3 scripts/check_install_pins.py; then
    DRIFT_FOUND=1
fi

if [ "${DRIFT_FOUND}" -ne 0 ]; then
    echo "Lockfile drift detected. See diff output above."
    exit 1
fi

echo "All lockfiles are in sync."
