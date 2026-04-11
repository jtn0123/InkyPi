#!/usr/bin/env bash
# test_install_memcap.sh — 512 MB memory-cap smoke test for Pi Zero 2 W installs.
#
# Runs two phases inside memory-capped Docker containers:
#
#   Phase 2 — pip install under arm64 + 512 MB cap (the JTN-528 OOM regression
#             gate). Uses python:3.12-slim with --platform linux/arm64 so the
#             pip resolver fetches arm64 binary wheels from PyPI — replicating
#             the exact download + install step that OOM-killed pip on a Pi
#             Zero 2 W without zramswap. Exit 137 = OOM kill.
#
#   Phase 3 — web service boot probe under a 512 MB cap. Mounts the repo into a
#             standard Python container, installs deps, starts the InkyPi web
#             server, and polls /healthz, /, /playlist, and /api/plugins to
#             confirm the server comes up healthy within the Pi's RAM budget.
#             Runs on the host arch (no QEMU) for speed.
#
# Usage:
#   ./scripts/test_install_memcap.sh [trixie|bookworm|bullseye]
#   ./scripts/test_install_memcap.sh --help
#
# Defaults to trixie when no codename is supplied (matches the Dockerfile.sim-install
# default used by the companion sim_install.sh tool).
set -euo pipefail

VALID_CODENAMES="trixie bookworm bullseye"
DEFAULT_CODENAME="trixie"
POLL_INTERVAL=5
POLL_MAX=60

usage() {
    echo "Usage: $(basename "${0}") [--help] [trixie|bookworm|bullseye]"
    echo ""
    echo "  Phase 2: pip install of requirements.txt under arm64 + 512 MB cap."
    echo "           Exit 137 = OOM kill = JTN-528 regression."
    echo "  Phase 3: web service boot + route probe under 512 MB cap."
    echo ""
    echo "  Supported codenames: ${VALID_CODENAMES}"
    echo "  Default codename   : ${DEFAULT_CODENAME}"
    echo ""
    echo "NOTE: This is a simulation, not real hardware."
}

# ── argument handling ──────────────────────────────────────────────────────────
CODENAME="${DEFAULT_CODENAME}"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    usage
    exit 0
fi

if [[ "$#" -gt 1 ]]; then
    echo "ERROR: Too many arguments." >&2
    echo "" >&2
    usage >&2
    exit 1
fi

if [[ -n "${1:-}" ]]; then
    CODENAME="${1}"
    valid=0
    for name in ${VALID_CODENAMES}; do
        if [[ "${CODENAME}" == "${name}" ]]; then
            valid=1
            break
        fi
    done
    if [[ "${valid}" -eq 0 ]]; then
        echo "ERROR: Unknown codename '${CODENAME}'." >&2
        echo "Valid options: ${VALID_CODENAMES}" >&2
        echo "" >&2
        usage >&2
        exit 1
    fi
fi

# ── locate repo root ───────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ── banner ────────────────────────────────────────────────────────────────────
echo "======================================================================"
echo "  InkyPi 512 MB memory-cap install + boot smoke test"
echo "  Codename : ${CODENAME}"
echo "  Repo root: ${REPO_ROOT}"
echo ""
echo "  Simulates Pi Zero 2 W RAM budget (512 MB, no swap headroom)."
echo "======================================================================"
echo ""

# ── Phase 2: pip install under arm64 + 512 MB cap ─────────────────────────────
# This is the core OOM regression gate (JTN-528 / JTN-536).
#
# On a Pi Zero 2 W without zramswap, pip install of numpy/Pillow was killed by
# the OOM killer (exit 137). The 512 MB cap plus arm64 emulation replicates
# that exact pressure — if the requirements grow too large, pip will be
# killed again and this job will fail with exit 137.
#
# We use python:3.12-slim (arm64) so Python is pre-installed and pip can
# fetch arm64 binary wheels directly without needing the full sim image.
echo "[Phase 2] Running pip install under arm64 + 512 MB memory cap ..."
echo "          Exit 137 = OOM kill (the JTN-528 regression mode)."
echo ""

PIP_EXIT=0
if docker run \
    --rm \
    --platform linux/arm64 \
    --memory=512m \
    --memory-swap=512m \
    -v "${REPO_ROOT}:/InkyPi:ro" \
    python:3.12-slim \
    bash -c '
set -euo pipefail
echo "Architecture : $(uname -m)"
echo "Python       : $(python3 --version)"
echo ""
echo "Installing runtime requirements under 512 MB arm64 cap ..."
pip install \
    --retries 5 \
    --timeout 120 \
    -r /InkyPi/install/requirements.txt \
    -q
echo ""
echo "pip install completed successfully inside 512 MB arm64 cap."
'; then
    PIP_EXIT=0
else
    PIP_EXIT=$?
fi

if [[ "${PIP_EXIT}" -ne 0 ]]; then
    echo "" >&2
    echo "ERROR: pip install failed under the 512 MB arm64 cap (exit ${PIP_EXIT})." >&2
    if [[ "${PIP_EXIT}" -eq 137 ]]; then
        echo "  Exit 137 = OOM kill — this is the JTN-528 regression." >&2
    fi
    echo "This mirrors what happens on a Pi Zero 2 W without sufficient swap." >&2
    exit "${PIP_EXIT}"
fi

echo ""
echo "[Phase 2] pip install OK under arm64 + 512 MB cap."
echo ""

# ── Phase 3: web service boot probe under 512 MB cap ─────────────────────────
# Start the InkyPi web server inside a memory-capped container (host arch for
# speed — no QEMU). Poll key routes to confirm the server comes up cleanly
# within the Pi's 512 MB budget.
CONTAINER_NAME="inkypi-memcap-smoke-$$"

echo "[Phase 3] Starting web service under 512 MB cap ..."

docker run \
    --rm \
    --detach \
    --name "${CONTAINER_NAME}" \
    --memory=512m \
    --memory-swap=512m \
    -p 18080:8080 \
    -e INKYPI_ENV=dev \
    -e INKYPI_NO_REFRESH=1 \
    -e PYTHONPATH=/app/src \
    -v "${REPO_ROOT}:/app:ro" \
    python:3.12-slim \
    bash -c '
cd /app
apt-get update -qq 2>/dev/null
apt-get install -y -qq libopenjp2-7 libfreetype6 2>/dev/null || true
pip install -r install/requirements.txt -q --quiet
python src/inkypi.py --dev --web-only
'

cleanup() {
    echo ""
    echo "[Cleanup] Stopping container ${CONTAINER_NAME} ..."
    docker stop "${CONTAINER_NAME}" 2>/dev/null || true
    docker rm -f "${CONTAINER_NAME}" 2>/dev/null || true
}
trap cleanup EXIT

echo "[Phase 3] Container started. Polling http://localhost:18080/healthz ..."
echo ""

# Poll until the server is up
SERVER_UP=0
elapsed=0
while [[ "${elapsed}" -lt "${POLL_MAX}" ]]; do
    STATUS=$(curl -o /dev/null -s -w "%{http_code}" --max-time 3 "http://localhost:18080/healthz" 2>/dev/null || true)
    if [[ "${STATUS}" == "200" ]]; then
        SERVER_UP=1
        echo "  /healthz → ${STATUS} (server up after ~${elapsed}s)"
        break
    fi
    echo "  /healthz → ${STATUS:-no-response} (${elapsed}s elapsed, retrying in ${POLL_INTERVAL}s)"
    sleep "${POLL_INTERVAL}"
    elapsed=$(( elapsed + POLL_INTERVAL ))
done

if [[ "${SERVER_UP}" -eq 0 ]]; then
    echo "" >&2
    echo "ERROR: Server did not respond at /healthz within ${POLL_MAX}s." >&2
    echo "" >&2
    echo "--- Container logs ---" >&2
    docker logs "${CONTAINER_NAME}" 2>&1 || true
    exit 1
fi

echo ""
echo "[Phase 3] Probing key routes ..."
echo ""

PROBE_FAILED=0

probe_route() {
    local path="${1}"
    local expected="${2}"   # e.g. "200" or "200|302"
    local url="http://localhost:18080${path}"
    local code
    code=$(curl -o /dev/null -s -w "%{http_code}" --max-time 5 "${url}" 2>/dev/null || true)
    # Check if code matches any of the pipe-separated expected codes
    local match=0
    local exp_list
    IFS='|' read -ra exp_list <<< "${expected}"
    local e
    for e in "${exp_list[@]}"; do
        if [[ "${code}" == "${e}" ]]; then
            match=1
            break
        fi
    done
    if [[ "${match}" -eq 1 ]]; then
        echo "  PASS  ${path} → ${code}"
    else
        echo "  FAIL  ${path} → ${code} (expected ${expected})" >&2
        PROBE_FAILED=1
    fi
}

probe_route "/healthz"       "200"
probe_route "/"              "200"
probe_route "/playlist"      "200|302"
probe_route "/api/plugins"   "200"

echo ""

if [[ "${PROBE_FAILED}" -ne 0 ]]; then
    echo "--- Container logs ---" >&2
    docker logs "${CONTAINER_NAME}" 2>&1 || true
    echo "" >&2
    echo "ERROR: One or more route probes failed — see above." >&2
    exit 1
fi

echo "======================================================================"
echo "  All checks passed."
echo "  Phase 2: pip install OK under arm64 + 512 MB cap"
echo "  Phase 3: web service boot + routes OK under 512 MB cap"
echo ""
echo "  REMINDER: This is a simulation. Always test on real Pi Zero 2 W"
echo "  hardware before shipping install path changes."
echo "======================================================================"
