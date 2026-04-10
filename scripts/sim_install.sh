#!/usr/bin/env bash
# sim_install.sh — Run install/install.sh inside an arm64 container that
# mimics the Pi Zero 2 W environment, without real hardware.
#
# Usage:
#   ./scripts/sim_install.sh [trixie|bookworm|bullseye]
#   ./scripts/sim_install.sh --help
#
# Defaults to trixie when no codename is supplied.
set -euo pipefail

VALID_CODENAMES="trixie bookworm bullseye"
DEFAULT_CODENAME="trixie"

usage() {
    echo "Usage: $(basename "${0}") [--help] [trixie|bookworm|bullseye]"
    echo ""
    echo "  Builds a local arm64 Docker image that mimics the Pi Zero 2 W and"
    echo "  runs install/install.sh end-to-end against the current checkout."
    echo ""
    echo "  Supported codenames: ${VALID_CODENAMES}"
    echo "  Default codename   : ${DEFAULT_CODENAME}"
    echo ""
    echo "NOTE: This is a simulation, not real hardware."
    echo "Always test on a real Pi Zero 2 W before merging install path changes."
}

# ── argument handling ─────────────────────────────────────────────────────────
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

# ── locate repo root ──────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ── banner ────────────────────────────────────────────────────────────────────
echo "======================================================================"
echo "  InkyPi install.sh simulator"
echo "  Codename : ${CODENAME}"
echo "  Repo root: ${REPO_ROOT}"
echo ""
echo "  NOTE: This is a SIMULATION only — not real hardware."
echo "  The container mimics a Pi Zero 2 W (arm64, 512 MB RAM)."
echo "======================================================================"
echo ""

IMAGE_TAG="inkypi-sim:${CODENAME}"
DOCKERFILE="${SCRIPT_DIR}/Dockerfile.sim-install"

# ── build ─────────────────────────────────────────────────────────────────────
echo "Building image ${IMAGE_TAG} ..."
docker build \
    --platform linux/arm64 \
    -f "${DOCKERFILE}" \
    --build-arg "CODENAME=${CODENAME}" \
    -t "${IMAGE_TAG}" \
    "${REPO_ROOT}"

echo ""
echo "Running install.sh in container (platform=linux/arm64, memory=512m) ..."
echo ""

# ── run ───────────────────────────────────────────────────────────────────────
# Use an explicit if/else so RUN_EXIT is always set regardless of set -e.
if docker run \
    --rm \
    --platform linux/arm64 \
    --memory=512m \
    --memory-swap=512m \
    "${IMAGE_TAG}"; then
    RUN_EXIT=0
else
    RUN_EXIT=$?
fi

# ── footer ────────────────────────────────────────────────────────────────────
echo ""
if [[ "${RUN_EXIT}" -eq 0 ]]; then
    echo "======================================================================"
    echo "  Simulation completed successfully."
    echo ""
    echo "  REMINDER: Run on a real Pi Zero 2 W before merging install path"
    echo "  changes — the sim does not exercise real GPIO, display hardware,"
    echo "  or systemd service activation."
    echo "======================================================================"
fi

exit "${RUN_EXIT}"
