#!/usr/bin/env bash
# test_install_memcap.sh — 512 MB memory-cap smoke test for Pi Zero 2 W installs.
#
# Runs two phases inside memory-capped Docker containers:
#
#   Phase 2 — pip install under a 512 MB memory cap.
#             Installs install/requirements.txt inside a capped container so any
#             OOM-kill of pip (the JTN-528 symptom) is caught immediately.
#             Uses the existing scripts/Dockerfile.sim-install arm64 image to
#             exercise the correct dependency set; arm64 wheels are fetched from
#             PyPI so no cross-compilation is needed.
#
#   Phase 3 — web service boot probe under a 512 MB cap.
#             Mounts the repo into a standard Python container, installs deps,
#             starts the InkyPi web server, and polls /healthz, /, /playlist,
#             and /api/plugins to confirm the server comes up healthy within the
#             Pi Zero 2 W RAM budget.
#
# Usage:
#   ./scripts/test_install_memcap.sh [trixie|bookworm|bullseye]
#   ./scripts/test_install_memcap.sh --help
#
# Defaults to trixie when no codename is supplied.
set -euo pipefail

VALID_CODENAMES="trixie bookworm bullseye"
DEFAULT_CODENAME="trixie"
POLL_INTERVAL=5
POLL_MAX=60

usage() {
    echo "Usage: $(basename "${0}") [--help] [trixie|bookworm|bullseye]"
    echo ""
    echo "  Phase 2: pip install under a 512 MB cap (OOM regression gate)."
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

IMAGE_TAG="inkypi-sim:${CODENAME}"
DOCKERFILE="${SCRIPT_DIR}/Dockerfile.sim-install"

# ── Phase 1: build the sim image ──────────────────────────────────────────────
echo "[Phase 1] Building sim image ${IMAGE_TAG} (platform: linux/arm64) ..."
docker build \
    --platform linux/arm64 \
    -f "${DOCKERFILE}" \
    --build-arg "CODENAME=${CODENAME}" \
    -t "${IMAGE_TAG}" \
    "${REPO_ROOT}"
echo "[Phase 1] Image built OK."
echo ""

# ── Phase 2: pip install under arm64 + 512 MB cap ─────────────────────────────
# This is the core OOM regression gate. On a Pi Zero 2 W without zramswap,
# pip install of numpy/Pillow was OOM-killed (JTN-528). The 512 MB cap
# reproduces that exact pressure. Pre-built arm64 wheels are fetched from
# PyPI — no cross-compilation is needed.
#
# If pip is killed by the OOM killer the exit code will be 137, which
# propagates through docker run and out of this script.
echo "[Phase 2] Running pip install under arm64 + 512 MB memory cap ..."
echo "          Exit 137 = OOM kill (the JTN-528 regression mode)."
echo ""

PIP_EXIT=0
if docker run \
    --rm \
    --platform linux/arm64 \
    --memory=512m \
    --memory-swap=512m \
    "${IMAGE_TAG}" \
    bash -c '
set -euo pipefail
cd /InkyPi
echo "Python version: $(python3 --version)"
python3 -m venv /tmp/pip-test-venv
/tmp/pip-test-venv/bin/python -m pip install --upgrade pip setuptools wheel -q
echo "Installing runtime requirements under 512 MB arm64 cap..."
/tmp/pip-test-venv/bin/python -m pip install \
    --retries 5 \
    --timeout 120 \
    -r install/requirements.txt \
    -q
echo "pip install completed successfully."
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
# Mount the repo into a standard Python container capped at 512 MB, install
# deps, and start the web server. Poll key routes to confirm the server boots
# cleanly within the Pi's memory budget. Running on the host arch avoids QEMU
# overhead while still enforcing the memory limit.
CONTAINER_NAME="inkypi-memcap-smoke-$$"

echo "[Phase 3] Starting web service under 512 MB cap (mount + host arch) ..."

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
apt-get update -qq && apt-get install -y -qq libopenjp2-7 libfreetype6 2>/dev/null || true
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
