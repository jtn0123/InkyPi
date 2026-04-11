#!/usr/bin/env bash
# test_install_memcap.sh — 512 MB memory-cap smoke test for Pi Zero 2 W installs.
#
# Runs three phases inside memory-capped Docker containers:
#
#   Phase 2 — pip install under a strict 512 MB memory cap (the JTN-528 OOM
#             regression gate). Installs install/requirements.txt inside a
#             capped Python container. Exit 137 = OOM kill = regression.
#
#   Phase 3 — web service boot probe under a 512 MB cap. Mounts the repo into a
#             standard Python container, installs deps, starts the InkyPi web
#             server, and polls /healthz, /, /playlist, and /api/plugins to
#             confirm the server comes up healthy within the Pi's RAM budget.
#             Runs on the host arch (no QEMU) for speed.
#
#   Phase 4 — RSS budget gate (JTN-608). Samples VmRSS of the web service from
#             /proc/1/status inside the container after a 30s idle settle and
#             again after exercising the render-adjacent routes. Fails CI when
#             the running service exceeds the Pi Zero 2 W memory envelope even
#             though install.sh and the boot probes pass (the regression mode
#             where baseline RSS balloons past MemoryMax=350M).
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
POLL_MAX=180
LOG_DIR="${TMPDIR:-/tmp}/inkypi-smoke-logs"
mkdir -p "${LOG_DIR}"

usage() {
    echo "Usage: $(basename "${0}") [--help] [trixie|bookworm|bullseye]"
    echo ""
    echo "  Phase 2: pip install of requirements.txt under 512 MB cap."
    echo "           Exit 137 = OOM kill = JTN-528 regression."
    echo "  Phase 3: web service boot + route probe under 512 MB cap."
    echo "  Phase 4: RSS budget gate (JTN-608) — idle <200 MB, peak <300 MB."
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
# the OOM killer (exit 137). The 512 MB cap replicates that exact pressure —
# if the requirements grow too large, pip will be killed again and this job
# will fail with exit 137.
echo "[Phase 2] Running pip install under 512 MB memory cap ..."
echo "          Exit 137 = OOM kill (the JTN-528 regression mode)."
echo ""

PIP_EXIT=0
if docker run \
    --rm \
    --memory=512m \
    --memory-swap=512m \
    -v "${REPO_ROOT}:/InkyPi:ro" \
    python:3.12-slim \
    bash -c '
set -euo pipefail
echo "Architecture : $(uname -m)"
echo "Python       : $(python3 --version)"
echo ""
# Install OS libraries required by packages that need to compile C extensions
# (inky / spidev / cysystemd / pi-heif) — mirrors what install.sh installs
# via debian-requirements.txt on a real Pi.
apt-get update -qq 2>/dev/null
apt-get install -y -qq \
    gcc \
    python3-dev \
    libopenjp2-7-dev \
    libfreetype6-dev \
    libsystemd-dev \
    libheif-dev \
    swig \
    2>/dev/null || true
echo ""
echo "Installing runtime requirements under 512 MB cap ..."
# --prefer-binary avoids source compilation where a binary wheel exists.
# Any remaining OOM kill (exit 137) signals the JTN-528 regression.
pip install \
    --retries 5 \
    --timeout 120 \
    --prefer-binary \
    -r /InkyPi/install/requirements.txt \
    -q
echo ""
echo "pip install completed successfully inside 512 MB cap."
'; then
    PIP_EXIT=0
else
    PIP_EXIT=$?
fi

if [[ "${PIP_EXIT}" -ne 0 ]]; then
    echo "" >&2
    echo "ERROR: pip install failed under the 512 MB cap (exit ${PIP_EXIT})." >&2
    if [[ "${PIP_EXIT}" -eq 137 ]]; then
        echo "  Exit 137 = OOM kill — this is the JTN-528 regression." >&2
    fi
    echo "This mirrors what happens on a Pi Zero 2 W without sufficient swap." >&2
    exit "${PIP_EXIT}"
fi

echo ""
echo "[Phase 2] pip install OK under 512 MB cap."
echo ""

# ── Phase 3: web service boot probe under 512 MB cap ─────────────────────────
# Build a container image with deps pre-installed, then start it with only
# the web server process. Separating build from run ensures the container is
# immediately serving when detached (no pip install delay during the poll).
PHASE3_IMAGE="inkypi-memcap-server-$$"
CONTAINER_NAME="inkypi-memcap-smoke-$$"

echo "[Phase 3] Building web service container image ..."
docker build \
    --quiet \
    -f - \
    -t "${PHASE3_IMAGE}" \
    "${REPO_ROOT}" <<'DOCKERFILE'
FROM python:3.12-slim
RUN apt-get update -qq \
    && apt-get install -y -qq gcc python3-dev libopenjp2-7-dev libfreetype6-dev libsystemd-dev libheif-dev swig 2>/dev/null \
    && rm -rf /var/lib/apt/lists/*
COPY install/requirements.txt /tmp/requirements.txt
RUN pip install --prefer-binary --quiet -r /tmp/requirements.txt
COPY . /app
WORKDIR /app
ENV INKYPI_ENV=dev
ENV INKYPI_NO_REFRESH=1
ENV PYTHONPATH=/app/src
# JTN-613: enable the opt-in smoke render endpoint (/__smoke/render) so Phase 4
# can actually call plugin.generate_image() in-process instead of bouncing off
# CSRF on /update_now. The endpoint is registered ONLY when this var is set;
# production builds (install.sh, inkypi.service) never set it.
ENV INKYPI_SMOKE_FORCE_RENDER=1
CMD ["python", "src/inkypi.py", "--dev", "--web-only"]
DOCKERFILE

echo "[Phase 3] Starting web service under 512 MB cap ..."

docker run \
    --rm \
    --detach \
    --name "${CONTAINER_NAME}" \
    --memory=512m \
    --memory-swap=512m \
    -p 18080:8080 \
    "${PHASE3_IMAGE}"

phase3_cleanup() {
    echo ""
    echo "[Cleanup] Stopping container ${CONTAINER_NAME} ..."
    docker stop "${CONTAINER_NAME}" 2>/dev/null || true
    docker rm -f "${CONTAINER_NAME}" 2>/dev/null || true
    docker rmi "${PHASE3_IMAGE}" 2>/dev/null || true
}

trap phase3_cleanup EXIT

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
    docker logs "${CONTAINER_NAME}" 2>&1 | tee "${LOG_DIR}/container.log" >&2 || true
    echo "Diagnostics saved to ${LOG_DIR}" >&2
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

probe_route "/healthz"            "200"
probe_route "/"                   "200"
probe_route "/playlist"           "200"
probe_route "/api/health/plugins" "200"

echo ""

if [[ "${PROBE_FAILED}" -ne 0 ]]; then
    echo "--- Container logs ---" >&2
    docker logs "${CONTAINER_NAME}" 2>&1 | tee "${LOG_DIR}/container.log" >&2 || true
    echo "Diagnostics saved to ${LOG_DIR}" >&2
    echo "" >&2
    echo "ERROR: One or more route probes failed — see above." >&2
    exit 1
fi

# ── Phase 4: RSS budget checks (JTN-608) ─────────────────────────────────────
# Asserts the running web service stays within the Pi Zero 2 W memory envelope.
# A Pi Zero 2 W has 512 MB RAM and the systemd unit caps InkyPi at MemoryMax=350M,
# so a service that idles around 250 MB in CI would OOM on the real hardware even
# though install.sh and the initial boot probes pass.
#
# Budgets (see docs/testing.md "CI memory budgets"):
#   Post-install idle RSS          : target <150 MB / hard fail 200 MB
#   Peak RSS during plugin render  : target <250 MB / hard fail 300 MB
#
# RSS is read from /proc/1/status (VmRSS) inside the container. The python
# process is PID 1 because it is the container's CMD. /proc avoids requiring
# `ps` / procps in the slim base image.
#
# JTN-613 sanity gate: peak must be at least PEAK_RSS_MIN_DELTA_MB larger than
# idle. If they come back equal, the harness is broken — the render path did
# not actually run — and we fail loud instead of silently passing the budget.
IDLE_RSS_HARD_MB=200
PEAK_RSS_HARD_MB=300
PEAK_RSS_MIN_DELTA_MB=5

read_container_rss_mb() {
    # Echoes the VmRSS of PID 1 inside the container, in MB (integer).
    # Returns empty string on failure so the caller can handle it.
    local rss_kb
    rss_kb=$(docker exec "${CONTAINER_NAME}" \
        sh -c "awk '/^VmRSS:/ {print \$2}' /proc/1/status" 2>/dev/null || true)
    if [[ -z "${rss_kb}" ]]; then
        echo ""
        return
    fi
    echo $(( rss_kb / 1024 ))
}

echo "[Phase 4] RSS budget checks (JTN-608)"
echo "[Phase 4] Letting the service settle for 30s before sampling idle RSS ..."
sleep 30

IDLE_RSS_MB=$(read_container_rss_mb)
if [[ -z "${IDLE_RSS_MB}" ]]; then
    echo "" >&2
    echo "ERROR: Could not read /proc/1/status from container." >&2
    docker logs "${CONTAINER_NAME}" 2>&1 | tee "${LOG_DIR}/container.log" >&2 || true
    exit 1
fi

echo "BUDGET CHECK: post-install idle RSS = ${IDLE_RSS_MB} MB (hard fail > ${IDLE_RSS_HARD_MB} MB)"

if [[ "${IDLE_RSS_MB}" -gt "${IDLE_RSS_HARD_MB}" ]]; then
    echo "" >&2
    echo "ERROR: idle RSS ${IDLE_RSS_MB} MB exceeds the ${IDLE_RSS_HARD_MB} MB hard budget." >&2
    echo "       This would OOM on a Pi Zero 2 W (MemoryMax=350M) after the refresh task starts." >&2
    docker logs "${CONTAINER_NAME}" 2>&1 | tee "${LOG_DIR}/container.log" >&2 || true
    exit 1
fi

echo "[Phase 4] Exercising plugin-render path to measure peak RSS ..."
# Hit render-adjacent routes plus the opt-in /__smoke/render endpoint (JTN-613)
# to drive the hottest codepath the idle service has.
#
# Prior to JTN-613 this section POSTed to /update_now, but /update_now requires
# a CSRF token so the POST was rejected with 403 before ever reaching plugin
# code — idle and peak came back identical because generate_image() never ran.
#
# /__smoke/render is registered only when INKYPI_SMOKE_FORCE_RENDER=1 (set in
# the Phase 3 Dockerfile above), is CSRF-exempt, and calls plugin.generate_image()
# in-process so the allocation happens inside PID 1 where read_container_rss_mb
# can observe it.
curl -fsS "http://localhost:18080/"                   -o /dev/null --max-time 10 || true
curl -fsS "http://localhost:18080/playlist"           -o /dev/null --max-time 10 || true
curl -fsS "http://localhost:18080/api/plugins"        -o /dev/null --max-time 10 || true
curl -fsS "http://localhost:18080/api/health/plugins" -o /dev/null --max-time 10 || true

# Render the clock plugin several times so peak RSS reflects the sustained
# working set, not just a one-off allocation that Python immediately frees.
# Clock has no external HTTP deps so it renders deterministically in CI.
SMOKE_RENDER_STATUS=""
for _ in 1 2 3; do
    SMOKE_RENDER_STATUS=$(curl -sS -o "${LOG_DIR}/smoke-render.json" -w "%{http_code}" \
        -X POST "http://localhost:18080/__smoke/render" \
        --max-time 20 \
        -H "Content-Type: application/x-www-form-urlencoded" \
        --data "plugin_id=clock" || true)
done
echo "[Phase 4] /__smoke/render last status: ${SMOKE_RENDER_STATUS:-unknown}"
if [[ "${SMOKE_RENDER_STATUS}" != "200" ]]; then
    echo "" >&2
    echo "ERROR: /__smoke/render did not return 200 (got '${SMOKE_RENDER_STATUS}')." >&2
    echo "       The render path was not actually exercised — peak RSS sample is invalid." >&2
    echo "       Response body:" >&2
    cat "${LOG_DIR}/smoke-render.json" 2>/dev/null | head -20 >&2 || true
    echo "" >&2
    docker logs "${CONTAINER_NAME}" 2>&1 | tee "${LOG_DIR}/container.log" >&2 || true
    exit 1
fi

echo "[Phase 4] Sleeping 10s to let peak-RSS settle ..."
sleep 10

PEAK_RSS_MB=$(read_container_rss_mb)
if [[ -z "${PEAK_RSS_MB}" ]]; then
    echo "" >&2
    echo "ERROR: Could not read /proc/1/status from container for peak sample." >&2
    docker logs "${CONTAINER_NAME}" 2>&1 | tee "${LOG_DIR}/container.log" >&2 || true
    exit 1
fi

echo "BUDGET CHECK: peak RSS after render exercise = ${PEAK_RSS_MB} MB (hard fail > ${PEAK_RSS_HARD_MB} MB)"

if [[ "${PEAK_RSS_MB}" -gt "${PEAK_RSS_HARD_MB}" ]]; then
    echo "" >&2
    echo "ERROR: peak RSS ${PEAK_RSS_MB} MB exceeds the ${PEAK_RSS_HARD_MB} MB hard budget." >&2
    echo "       A plugin render that allocates this much will OOM on the Pi Zero 2 W." >&2
    docker logs "${CONTAINER_NAME}" 2>&1 | tee "${LOG_DIR}/container.log" >&2 || true
    exit 1
fi

# JTN-613 sanity gate: if peak == idle (or within MIN_DELTA_MB), the render
# exercise never actually ran and the peak budget is silently useless. Fail
# loud so a future regression that breaks the harness surfaces immediately
# instead of hiding behind a "budgets OK" green check.
RSS_DELTA_MB=$(( PEAK_RSS_MB - IDLE_RSS_MB ))
echo "BUDGET CHECK: peak-vs-idle RSS delta = ${RSS_DELTA_MB} MB (sanity floor >= ${PEAK_RSS_MIN_DELTA_MB} MB)"
if [[ "${RSS_DELTA_MB}" -lt "${PEAK_RSS_MIN_DELTA_MB}" ]]; then
    echo "" >&2
    echo "ERROR: peak RSS (${PEAK_RSS_MB} MB) is not meaningfully greater than idle RSS" >&2
    echo "       (${IDLE_RSS_MB} MB) — delta ${RSS_DELTA_MB} MB < ${PEAK_RSS_MIN_DELTA_MB} MB floor." >&2
    echo "       The render exercise loop did not actually allocate any Pillow buffers." >&2
    echo "       This is the JTN-613 regression mode: the peak budget becomes silently" >&2
    echo "       equivalent to the idle budget and stops catching render-path leaks." >&2
    docker logs "${CONTAINER_NAME}" 2>&1 | tee "${LOG_DIR}/container.log" >&2 || true
    exit 1
fi

echo ""
echo "[Phase 4] RSS budgets OK."
echo "         idle  = ${IDLE_RSS_MB} MB / ${IDLE_RSS_HARD_MB} MB"
echo "         peak  = ${PEAK_RSS_MB} MB / ${PEAK_RSS_HARD_MB} MB"
echo "         delta = ${RSS_DELTA_MB} MB (render exercise confirmed, JTN-613)"
echo ""

echo "======================================================================"
echo "  All checks passed."
echo "  Phase 2: pip install OK under 512 MB cap"
echo "  Phase 3: web service boot + routes OK under 512 MB cap"
echo "  Phase 4: RSS budgets (idle ${IDLE_RSS_MB} MB, peak ${PEAK_RSS_MB} MB) OK"
echo ""
echo "  REMINDER: This is a simulation. Always test on real Pi Zero 2 W"
echo "  hardware before shipping install path changes."
echo "======================================================================"
