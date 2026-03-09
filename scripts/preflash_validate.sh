#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${SCRIPT_DIR}/.."
cd "${REPO_ROOT}" || exit 1

if [[ ! -f ".venv/bin/activate" || ! -x ".venv/bin/python" ]]; then
    echo "FAIL venv      .venv is required; run 'scripts/venv.sh' first" >&2
    exit 1
fi

# shellcheck source=/dev/null
source ".venv/bin/activate"
export PYTHONPATH="src${PYTHONPATH:+:$PYTHONPATH}"

status_ok() {
    printf 'PASS %-10s %s\n' "$1" "$2"
}

status_fail() {
    printf 'FAIL %-10s %s\n' "$1" "$2" >&2
}

status_skip() {
    printf 'SKIP %-10s %s\n' "$1" "$2"
}

run_phase() {
    local phase="$1"
    shift
    if "$@"; then
        status_ok "${phase}" "ok"
    else
        status_fail "${phase}" "failed"
        return 1
    fi
}

syntax_check() {
    bash -n install/install.sh
    bash -n install/update.sh
    bash -n install/uninstall.sh
}

import_smoke_check() {
    local temp_dir
    local venv_python
    temp_dir="$(mktemp -d "${TMPDIR:-/tmp}/inkypi-import-smoke.XXXXXX")"
    trap 'rm -rf "${temp_dir:-}"' RETURN

    python3 -m venv "${temp_dir}/venv"
    venv_python="${temp_dir}/venv/bin/python"
    "${venv_python}" -m pip install -U pip wheel >/dev/null
    "${venv_python}" -m pip install -r install/requirements.txt >/dev/null
    "${venv_python}" -m pip check >/dev/null
    "${venv_python}" scripts/preflash_smoke.py imports
}

run_phase "syntax" syntax_check

run_phase \
    "pytest" \
    python -m pytest -q \
    tests/unit/test_display_manager.py \
    tests/unit/test_config_resolution.py \
    tests/unit/test_inkypi.py \
    tests/unit/test_epdconfig.py

run_phase "app-smoke" python scripts/preflash_smoke.py app
run_phase "render-smoke" python scripts/preflash_smoke.py render

if [[ "${INKYPI_VALIDATE_INSTALL:-0}" == "1" ]]; then
    run_phase "imports" import_smoke_check
else
    status_skip "imports" "set INKYPI_VALIDATE_INSTALL=1 to run import smoke"
fi

printf 'PASS %-10s %s\n' "summary" "pre-flash validation complete"
