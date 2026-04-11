#!/usr/bin/env bash
# check_requirements_drift.sh — verify pip-compile lockfiles are in sync.
#
# Compares the pip-compile region of install/requirements.txt against a fresh
# pip-compile run.  The manually-appended Linux-only block at the bottom of
# requirements.txt (everything from the sentinel comment onwards) is excluded
# from the comparison because pip-compile cannot resolve linux-only packages
# when running on a non-Linux host.
#
# Usage:
#   scripts/check_requirements_drift.sh [--check-dev]
#
# Exits 0 when in sync, 1 when drift is detected.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REQ_IN="${REPO_ROOT}/install/requirements.in"
REQ_TXT="${REPO_ROOT}/install/requirements.txt"
REQ_DEV_IN="${REPO_ROOT}/install/requirements-dev.in"
REQ_DEV_TXT="${REPO_ROOT}/install/requirements-dev.txt"

# Sentinel that marks the start of the manually-maintained Linux-only block.
# Everything from this line onwards is excluded from the pip-compile comparison.
LINUX_BLOCK_SENTINEL="# ============================================================"

DRIFT_FOUND=0

pip_compile_check() {
    local in_file="$1"
    local committed_txt="$2"
    local label="$3"
    local strip_linux_block="${4:-false}"

    echo "==> Checking ${label} ..."

    local tmp_compiled
    tmp_compiled="$(mktemp /tmp/requirements-check-XXXXXX.txt)"
    local tmp_committed
    tmp_committed="$(mktemp /tmp/requirements-committed-XXXXXX.txt)"

    # Generate fresh lockfile into temp file
    pip-compile \
        --generate-hashes \
        --no-strip-extras \
        --allow-unsafe \
        --quiet \
        "${in_file}" \
        -o "${tmp_compiled}"

    # Normalise paths in the auto-generated header of the fresh output so that
    # absolute local paths match the relative paths recorded in the committed file.
    # The header line looks like:
    #   #    pip-compile ... --output-file=/tmp/xxx /abs/path/to/install/requirements.in
    # We replace both the temp output file path and the absolute input path with
    # the relative equivalents that pip-compile writes when run from the repo root.
    local rel_in
    rel_in="${in_file#"${REPO_ROOT}"/}"
    local rel_out
    rel_out="${committed_txt#"${REPO_ROOT}"/}"

    python3 - <<PY "${tmp_compiled}" "${tmp_compiled}.norm" "${tmp_compiled}" "${rel_out}" "${in_file}" "${rel_in}"
import sys
src, dst, tmp_compiled, rel_out, abs_in, rel_in = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6]
with open(src) as f:
    content = f.read()
# Replace absolute temp output path with relative committed path in header
content = content.replace("--output-file=" + tmp_compiled, "--output-file=" + rel_out)
# Replace absolute input path with relative path (header + via comments)
content = content.replace(abs_in, rel_in)
with open(dst, "w") as f:
    f.write(content)
PY
    mv "${tmp_compiled}.norm" "${tmp_compiled}"

    # Prepare the committed file for comparison
    if [ "${strip_linux_block}" = "true" ]; then
        # Strip everything from the Linux-only sentinel onwards
        python3 - <<PY "${committed_txt}" "${tmp_committed}" "${LINUX_BLOCK_SENTINEL}"
import sys

in_path, out_path, sentinel = sys.argv[1], sys.argv[2], sys.argv[3]
with open(in_path) as f:
    lines = f.readlines()

out_lines = []
for line in lines:
    if line.startswith(sentinel):
        break
    out_lines.append(line)

# Strip trailing blank lines so the diff is clean
while out_lines and out_lines[-1].strip() == "":
    out_lines.pop()

with open(out_path, "w") as f:
    f.writelines(out_lines)
PY
    else
        cp "${committed_txt}" "${tmp_committed}"
    fi

    # Normalise fresh output the same way (strip trailing blank lines)
    python3 - <<PY "${tmp_compiled}"
import sys

path = sys.argv[1]
with open(path) as f:
    lines = f.readlines()

while lines and lines[-1].strip() == "":
    lines.pop()

with open(path, "w") as f:
    f.writelines(lines)
PY

    if diff -u "${tmp_committed}" "${tmp_compiled}"; then
        echo "    OK — ${label} is up to date."
    else
        echo ""
        echo "ERROR: ${label} is out of sync with ${in_file}."
        echo "Run the following command to regenerate it and commit the result:"
        echo ""
        echo "  pip-compile --generate-hashes --no-strip-extras --allow-unsafe \\"
        echo "      ${in_file} -o ${committed_txt}"
        echo ""
        DRIFT_FOUND=1
    fi

    rm -f "${tmp_compiled}" "${tmp_committed}"
}

# Always check requirements.in → requirements.txt (strip Linux block)
pip_compile_check \
    "${REQ_IN}" \
    "${REQ_TXT}" \
    "install/requirements.txt" \
    "true"

# Check requirements-dev.in → requirements-dev.txt (no Linux block)
if [ -f "${REQ_DEV_IN}" ] && [ -f "${REQ_DEV_TXT}" ]; then
    pip_compile_check \
        "${REQ_DEV_IN}" \
        "${REQ_DEV_TXT}" \
        "install/requirements-dev.txt" \
        "false"
fi

if [ "${DRIFT_FOUND}" -ne 0 ]; then
    echo "One or more lockfiles are out of sync. See diff output above."
    exit 1
fi

echo "All lockfiles are in sync."
