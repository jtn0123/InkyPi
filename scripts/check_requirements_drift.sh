#!/usr/bin/env bash
# check_requirements_drift.sh — verify uv-exported lockfile is in sync.
#
# JTN-616: migrated from pip-compile to `uv lock` + `uv export`. The universal
# lockfile produced by uv resolves all supported platforms in a single file,
# which eliminates the previous pain points around:
#   - Python version mismatches (3.13 vs 3.12)
#   - sys_platform-gated packages (cysystemd, gpiod)
#   - Multi-arch wheel hash coverage (arm64/armv7l/aarch64)
#
# Source of truth: pyproject.toml + uv.lock.
# install/requirements.txt is regenerated from uv.lock via `uv export`.
#
# This script:
#   1. Ensures uv.lock is up to date with pyproject.toml (`uv lock --check`).
#   2. Regenerates install/requirements.txt into a temp file and diffs against
#      the committed copy.
#
# Usage:
#   scripts/check_requirements_drift.sh
#
# Exits 0 when in sync, 1 when drift is detected.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REQ_TXT="${REPO_ROOT}/install/requirements.txt"

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

echo "==> Checking install/requirements.txt matches uv export ..."
tmp_export="$(mktemp /tmp/requirements-check-XXXXXX.txt)"
trap 'rm -f "${tmp_export}"' EXIT

uv export \
    --format requirements.txt \
    --no-dev \
    --no-emit-project \
    --output-file "${tmp_export}" \
    --quiet

# Normalise the auto-generated header of the fresh export so that the temp
# output path in the header matches the relative committed path.
python3 - <<'PY' "${tmp_export}" "install/requirements.txt"
import sys
src, rel_out = sys.argv[1], sys.argv[2]
with open(src) as f:
    content = f.read()
lines = content.splitlines(keepends=True)
# Replace the command comment line with the canonical form that references the
# committed output path. Line 2 (index 1) is the command comment per uv's
# deterministic header layout.
for i, line in enumerate(lines):
    if line.startswith("#    uv export ") and "--output-file" in line:
        lines[i] = (
            "#    uv export --format requirements.txt --no-dev "
            "--no-emit-project --output-file " + rel_out + "\n"
        )
        break
with open(src, "w") as f:
    f.writelines(lines)
PY

if diff -u "${REQ_TXT}" "${tmp_export}"; then
    echo "    OK — install/requirements.txt is up to date."
else
    echo ""
    echo "ERROR: install/requirements.txt is out of sync with uv.lock."
    echo "Run the following command to regenerate it and commit the result:"
    echo ""
    echo "  uv export --format requirements.txt --no-dev --no-emit-project \\"
    echo "      --output-file install/requirements.txt"
    echo ""
    DRIFT_FOUND=1
fi

if [ "${DRIFT_FOUND}" -ne 0 ]; then
    echo "Lockfile drift detected. See diff output above."
    exit 1
fi

echo "All lockfiles are in sync."
