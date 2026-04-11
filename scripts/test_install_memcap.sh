#!/usr/bin/env bash
# test_install_memcap.sh — Run install.sh inside a 512 MB-capped arm64 container,
# then start the InkyPi web service and probe key routes.
#
# This catches OOM regressions (e.g. pip install killed, server OOM at boot)
# that would manifest on a real Pi Zero 2 W (512 MB RAM).
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
    echo "  Builds the sim image, then runs install.sh + a web-service probe"
    echo "  inside a 512 MB-capped arm64 container (matching Pi Zero 2 W RAM)."
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
echo "  Simulates Pi Zero 2 W (arm64, 512 MB RAM, no swap headroom)."
echo "======================================================================"
echo ""

IMAGE_TAG="inkypi-sim:${CODENAME}"
DOCKERFILE="${SCRIPT_DIR}/Dockerfile.sim-install"

# ── Phase 1: build image ───────────────────────────────────────────────────────
echo "[Phase 1] Building image ${IMAGE_TAG} ..."
docker build \
    --platform linux/arm64 \
    -f "${DOCKERFILE}" \
    --build-arg "CODENAME=${CODENAME}" \
    -t "${IMAGE_TAG}" \
    "${REPO_ROOT}"
echo "[Phase 1] Image built OK."
echo ""

# ── Phase 2: run install.sh under 512 MB cap ──────────────────────────────────
echo "[Phase 2] Running install.sh inside 512 MB-capped container ..."
echo ""

INSTALL_EXIT=0
if docker run \
    --rm \
    --platform linux/arm64 \
    --memory=512m \
    --memory-swap=512m \
    "${IMAGE_TAG}"; then
    INSTALL_EXIT=0
else
    INSTALL_EXIT=$?
fi

if [[ "${INSTALL_EXIT}" -ne 0 ]]; then
    echo "" >&2
    echo "ERROR: install.sh failed inside the 512 MB cap (exit ${INSTALL_EXIT})." >&2
    echo "This mirrors an OOM or install failure on a real Pi Zero 2 W." >&2
    exit "${INSTALL_EXIT}"
fi

echo ""
echo "[Phase 2] install.sh succeeded under 512 MB cap."
echo ""

# ── Phase 3: boot the web service and probe routes ────────────────────────────
# We need a long-running container: launch detached, poll from outside, then stop.
CONTAINER_NAME="inkypi-memcap-smoke-$$"

echo "[Phase 3] Starting web service container (512 MB cap, detached) ..."
docker run \
    --rm \
    --detach \
    --name "${CONTAINER_NAME}" \
    --platform linux/arm64 \
    --memory=512m \
    --memory-swap=512m \
    -p 18080:8080 \
    -e INKYPI_ENV=dev \
    -e INKYPI_NO_REFRESH=1 \
    -e PYTHONPATH=/InkyPi/src \
    --entrypoint /bin/bash \
    "${IMAGE_TAG}" \
    -c "cd /InkyPi && .venv/bin/python src/inkypi.py --dev --web-only"

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
    docker logs "${CONTAINER_NAME}" 2>&1 >&2 || true
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
    local exp
    IFS='|' read -ra exp <<< "${expected}"
    for e in "${exp[@]}"; do
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
    docker logs "${CONTAINER_NAME}" 2>&1 >&2 || true
    echo "" >&2
    echo "ERROR: One or more route probes failed — see above." >&2
    exit 1
fi

echo "======================================================================"
echo "  All checks passed: install.sh + web service boot under 512 MB cap."
echo ""
echo "  REMINDER: This is a simulation. Always test on real Pi Zero 2 W"
echo "  hardware before shipping install path changes."
echo "======================================================================"
