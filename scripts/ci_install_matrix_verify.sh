#!/usr/bin/env bash
# ci_install_matrix_verify.sh — run install/install.sh end-to-end inside the
# container built from scripts/Dockerfile.install-matrix and assert the result.
#
# Intended to be invoked by the `install-matrix` job in .github/workflows/ci.yml
# (JTN-530). Runs *inside* the container — the outer CI step uses
# `docker run --entrypoint bash ... -c 'bash /InkyPi/scripts/ci_install_matrix_verify.sh'`
# so this script always executes with the repo mounted at /InkyPi.
#
# Phases:
#   1. Run install.sh non-interactively and assert exit 0.
#   2. Assert the venv was created at /usr/local/inkypi/venv_inkypi.
#   3. Assert the venv imports flask, waitress, and PIL (Pillow) successfully.
#   4. Assert install/inkypi.service parses with `systemd-analyze verify`.
#
# Each phase prints a banner and a clear PASS/FAIL marker so CI logs are easy
# to scan when a regression is caught. Any failure exits immediately with a
# non-zero status so the matrix leg fails fast.
set -euo pipefail

APPNAME="inkypi"
INSTALL_PATH="/usr/local/${APPNAME}"
VENV_PATH="${INSTALL_PATH}/venv_${APPNAME}"
SERVICE_FILE="/InkyPi/install/inkypi.service"

banner() {
    echo ""
    echo "======================================================================"
    echo "  $1"
    echo "======================================================================"
}

pass() { echo "  PASS  $1"; }
fail() { echo "  FAIL  $1" >&2; exit 1; }

banner "Phase 1/4 — run install/install.sh end-to-end"
cd /InkyPi/install

# install.sh uses `tput` for coloured output; supply a sane TERM so it does not
# error out in the non-tty container environment.
export TERM="${TERM:-dumb}"

# Force the wheelhouse fetch off — we want to exercise the source pip install
# path (install_debian_dependencies + create_venv) which is what actually
# catches regressions like JTN-528's zramswap breakage on Trixie. A pre-built
# wheelhouse would mask a broken requirements.txt.
export INKYPI_SKIP_WHEELHOUSE=1

if ./install.sh; then
    pass "install.sh exited 0"
else
    rc=$?
    fail "install.sh exited ${rc}"
fi

banner "Phase 2/4 — assert venv was created"
if [ -d "${VENV_PATH}" ]; then
    pass "venv present at ${VENV_PATH}"
else
    fail "venv missing at ${VENV_PATH}"
fi

if [ -x "${VENV_PATH}/bin/python" ]; then
    pass "${VENV_PATH}/bin/python is executable"
else
    fail "${VENV_PATH}/bin/python is missing or not executable"
fi

banner "Phase 3/4 — assert venv imports flask, waitress, Pillow"
# Run each import in a single python invocation so we fail on the first missing
# dependency with a clear error. Using `python -c` keeps this portable.
if "${VENV_PATH}/bin/python" -c "import flask, waitress, PIL; print('flask', flask.__version__); print('waitress', waitress.__version__); print('Pillow', PIL.__version__)"; then
    pass "flask, waitress, Pillow importable from install venv"
else
    fail "one or more required packages missing from install venv"
fi

banner "Phase 4/4 — systemd-analyze verify install/inkypi.service"
# systemd-analyze verify does a static parse of the unit file. It does NOT
# require a running systemd. We pass the service file path directly so no
# system-wide unit lookup is attempted.
if systemd-analyze verify "${SERVICE_FILE}"; then
    pass "${SERVICE_FILE} parses cleanly"
else
    fail "${SERVICE_FILE} failed systemd-analyze verify"
fi

banner "All phases passed"
echo "install.sh end-to-end matrix verification complete."
