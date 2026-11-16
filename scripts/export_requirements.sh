#!/usr/bin/env bash
# export_requirements.sh — write the two hashed exports of uv.lock.
#
# install/requirements.txt is the runtime lock the Pi installs, and
# install/requirements-dev.txt is the runtime lock plus the dev group. Both
# come from uv.lock exactly as it stands (`--frozen`: uv never re-locks, and
# needs no network). The header names the committed path, wherever the file
# was written, so an export to a temporary file can be diffed against it.
#
# Usage:
#   scripts/export_requirements.sh                     # rewrite both files
#   scripts/export_requirements.sh RUNTIME_OUT DEV_OUT # write them elsewhere
#
# check_requirements_drift.sh uses the second form; the Dependabot exports
# workflow (.github/workflows/dependabot-exports.yml) uses the first.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: uv is not installed. Install the pinned copy with:" >&2
    echo "  python -m pip install --require-hashes -r install/uv-requirements.txt" >&2
    exit 1
fi

# export_lock OUTPUT COMMITTED_PATH UV_EXPORT_SELECTION...
export_lock() {
    local output="$1" committed="$2"
    shift 2
    uv export --frozen --format requirements.txt "$@" --no-emit-project \
        --output-file "${output}" --quiet
    # uv records its own command line in the header. Record the documented
    # command against the committed path instead.
    local header="#    uv export --format requirements.txt $* --no-emit-project --output-file ${committed}"
    local tmp
    tmp="$(mktemp "${output}.XXXXXX")"
    awk -v header="${header}" '
        !done && /^#    uv export .*--output-file/ { print header; done = 1; next }
        { print }
    ' "${output}" >"${tmp}"
    mv -f "${tmp}" "${output}"
}

export_lock "${1:-install/requirements.txt}" install/requirements.txt --no-dev
export_lock "${2:-install/requirements-dev.txt}" install/requirements-dev.txt --group dev
