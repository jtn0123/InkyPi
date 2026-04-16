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

is_truthy() {
    case "${1:-}" in
        1|true|TRUE|yes|YES|on|ON)
            return 0
            ;;
    esac
    return 1
}

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

stress_suite() {
    export INKYPI_PLUGIN_TIMEOUT_S="${INKYPI_PLUGIN_TIMEOUT_S:-10}"
    export INKYPI_PLUGIN_RETRY_MAX="${INKYPI_PLUGIN_RETRY_MAX:-0}"
    export INKYPI_HISTORY_MAX_ENTRIES="${INKYPI_HISTORY_MAX_ENTRIES:-20}"
    export PYTEST_ADDOPTS="${PYTEST_ADDOPTS:-}"
    python -m pytest -q \
        tests/unit/test_refresh_task_stress.py \
        tests/unit/test_memory_leaks.py
}

heavy_plugin_suite() {
    python -m pytest -q \
        tests/plugins/test_weather.py \
        tests/plugins/test_calendar.py \
        tests/plugins/test_ai_image.py \
        tests/plugins/test_ai_text.py \
        tests/plugins/test_screenshot.py \
        tests/plugins/test_image_album.py \
        tests/plugins/test_image_folder.py \
        tests/plugins/test_image_upload.py
}

isolation_suite() {
    export INKYPI_PLUGIN_TIMEOUT_S="${INKYPI_PLUGIN_TIMEOUT_S:-5}"
    export INKYPI_PLUGIN_RETRY_MAX="${INKYPI_PLUGIN_RETRY_MAX:-0}"
    python -m pytest -q \
        tests/unit/test_plugin_isolation.py \
        tests/unit/test_refresh_policy.py \
        tests/unit/test_refresh_task_unit.py \
        tests/integration/test_plugin_lifecycle_flow.py
}

fault_suite() {
    python -m pytest -q \
        tests/integration/chaos/ \
        tests/integration/test_error_injection.py \
        tests/integration/test_error_recovery.py \
        tests/unit/test_display_save_failure_isolation.py \
        tests/unit/test_validation_faults.py
}

upgrade_compat_suite() {
    python -m pytest -q \
        tests/unit/test_upgrade_compatibility.py \
        tests/unit/test_config_migration.py \
        tests/install/test_upgrade_chain.py
}

coverage_suite() {
    rm -f coverage.xml
    export INKYPI_PLUGIN_ISOLATION=none
    export INKYPI_NO_HOT_RELOAD=1
    python -m pytest \
        -q \
        --cov=src \
        --cov-branch \
        --cov-report=xml:coverage.xml \
        tests/unit/test_display_manager.py \
        tests/unit/test_display_manager_coverage.py \
        tests/unit/test_config_resolution.py \
        tests/unit/test_config_validation.py \
        tests/unit/test_config_fallbacks_extra.py \
        tests/unit/test_refresh_policy.py \
        tests/unit/test_refresh_task_helpers.py \
        tests/unit/test_refresh_task_execute.py \
        tests/unit/test_refresh_task_unit.py \
        tests/unit/test_refresh_task_resilience.py \
        tests/unit/test_plugin_isolation.py \
        tests/unit/test_upgrade_compatibility.py \
        tests/unit/test_install_scripts.py \
        tests/unit/test_config_mtime_cache.py
    python scripts/coverage_gate.py coverage.xml
}

security_suite() {
    mkdir -p artifacts/security
    python -m pip_audit -r install/requirements.txt --format=json \
        --output artifacts/security/pip-audit-runtime.json
    python -m pip_audit -r install/requirements-dev.txt --format=json \
        --output artifacts/security/pip-audit-dev.json
    python -m cyclonedx_py environment .venv/bin/python --of JSON \
        -o artifacts/security/sbom.json
}

flake_suite() {
    local _run_index
    for _run_index in 1 2 3; do
        python -m pytest -q \
            tests/unit/test_refresh_task_stress.py \
            tests/unit/test_memory_leaks.py \
            tests/unit/test_plugin_isolation.py \
            tests/unit/test_validation_faults.py \
            tests/plugins/test_weather.py \
            tests/plugins/test_calendar.py \
            tests/plugins/test_ai_image.py \
            tests/plugins/test_ai_text.py \
            tests/plugins/test_screenshot.py \
            tests/plugins/test_image_album.py \
            tests/plugins/test_image_folder.py \
            tests/plugins/test_image_upload.py
        if [[ "$(uname -s)" == "Linux" ]]; then
            REQUIRE_BROWSER_SMOKE=1 python -m pytest -q tests/integration/test_browser_smoke.py
        fi
    done
}

fs_permissions_suite() {
    python -m pytest -q tests/unit/test_filesystem_permission_validation.py
}

soak_suite() {
    python scripts/preflash_smoke.py soak
}

recovery_suite() {
    python -m pytest -q tests/unit/test_startup_recovery_validation.py
}

api_contract_suite() {
    python -m pytest -q tests/integration/test_api_contracts.py
}

mutation_suite() {
    python scripts/mutation_check.py
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

if is_truthy "${INKYPI_VALIDATE_PI_RUNTIME:-0}"; then
    if [[ "$(uname -s)" == "Linux" ]]; then
        run_phase "pi-runtime" python scripts/preflash_smoke.py pi-runtime
    else
        status_skip "pi-runtime" "Linux-only runtime smoke"
    fi
else
    status_skip "pi-runtime" "set INKYPI_VALIDATE_PI_RUNTIME=1 to run Pi-like runtime smoke"
fi

if is_truthy "${INKYPI_VALIDATE_STRESS:-0}"; then
    run_phase "stress" stress_suite
else
    status_skip "stress" "set INKYPI_VALIDATE_STRESS=1 to run low-memory stress lane"
fi

if is_truthy "${INKYPI_VALIDATE_HEAVY_PLUGINS:-0}"; then
    run_phase "heavy" heavy_plugin_suite
else
    status_skip "heavy" "set INKYPI_VALIDATE_HEAVY_PLUGINS=1 to run heavy plugin lane"
fi

if is_truthy "${INKYPI_VALIDATE_BENCH_THRESHOLDS:-0}"; then
    run_phase "benchmarks" python scripts/preflash_smoke.py benchmarks
else
    status_skip "benchmarks" "set INKYPI_VALIDATE_BENCH_THRESHOLDS=1 to run benchmark assertions"
fi

if is_truthy "${INKYPI_VALIDATE_COLD_BOOT:-0}"; then
    run_phase "cold-boot" python scripts/preflash_smoke.py cold-boot
else
    status_skip "cold-boot" "set INKYPI_VALIDATE_COLD_BOOT=1 to run cold-boot smoke"
fi

if is_truthy "${INKYPI_VALIDATE_CACHE:-0}"; then
    run_phase "cache" python scripts/preflash_smoke.py cache
else
    status_skip "cache" "set INKYPI_VALIDATE_CACHE=1 to run cache correctness lane"
fi

if is_truthy "${INKYPI_VALIDATE_ISOLATION:-0}"; then
    run_phase "isolation" isolation_suite
else
    status_skip "isolation" "set INKYPI_VALIDATE_ISOLATION=1 to run isolation lane"
fi

if is_truthy "${INKYPI_VALIDATE_BROWSER_RENDER:-0}"; then
    if [[ "$(uname -s)" == "Linux" ]]; then
        run_phase "browser" python scripts/preflash_smoke.py browser-render
    else
        status_skip "browser" "Linux-only browser render smoke"
    fi
else
    status_skip "browser" "set INKYPI_VALIDATE_BROWSER_RENDER=1 to run browser/render smoke"
fi

if is_truthy "${INKYPI_VALIDATE_INSTALL_IDEMPOTENCY:-0}"; then
    if [[ "$(uname -s)" == "Linux" ]]; then
        run_phase "install-idem" python scripts/preflash_smoke.py install-idempotency
        run_phase "install-tests" python -m pytest -q tests/unit/test_install_scripts.py
    else
        status_skip "install-idem" "Linux-only install/update idempotency lane"
    fi
else
    status_skip "install-idem" "set INKYPI_VALIDATE_INSTALL_IDEMPOTENCY=1 to run install/update idempotency lane"
fi

if is_truthy "${INKYPI_VALIDATE_FAULTS:-0}"; then
    run_phase "faults" fault_suite
else
    status_skip "faults" "set INKYPI_VALIDATE_FAULTS=1 to run fault-injection lane"
fi

if is_truthy "${INKYPI_VALIDATE_UPGRADE_COMPAT:-0}"; then
    run_phase "upgrade" upgrade_compat_suite
else
    status_skip "upgrade" "set INKYPI_VALIDATE_UPGRADE_COMPAT=1 to run upgrade compatibility lane"
fi

if is_truthy "${INKYPI_VALIDATE_COVERAGE:-0}"; then
    run_phase "coverage" coverage_suite
else
    status_skip "coverage" "set INKYPI_VALIDATE_COVERAGE=1 to run critical-path coverage gate"
fi

if is_truthy "${INKYPI_VALIDATE_SECURITY:-0}"; then
    run_phase "security" security_suite
else
    status_skip "security" "set INKYPI_VALIDATE_SECURITY=1 to run security and SBOM checks"
fi

if is_truthy "${INKYPI_VALIDATE_FLAKE:-0}"; then
    run_phase "flake" flake_suite
else
    status_skip "flake" "set INKYPI_VALIDATE_FLAKE=1 to run flaky-test detection"
fi

if is_truthy "${INKYPI_VALIDATE_FS_PERMS:-0}"; then
    run_phase "fs-perms" fs_permissions_suite
else
    status_skip "fs-perms" "set INKYPI_VALIDATE_FS_PERMS=1 to run filesystem-permission checks"
fi

if is_truthy "${INKYPI_VALIDATE_SOAK:-0}"; then
    run_phase "soak" soak_suite
else
    status_skip "soak" "set INKYPI_VALIDATE_SOAK=1 to run soak validation"
fi

if is_truthy "${INKYPI_VALIDATE_RECOVERY:-0}"; then
    run_phase "recovery" recovery_suite
else
    status_skip "recovery" "set INKYPI_VALIDATE_RECOVERY=1 to run startup-recovery checks"
fi

if is_truthy "${INKYPI_VALIDATE_API_CONTRACT:-0}"; then
    run_phase "api" api_contract_suite
else
    status_skip "api" "set INKYPI_VALIDATE_API_CONTRACT=1 to run API contract checks"
fi

if is_truthy "${INKYPI_VALIDATE_MUTATION:-0}"; then
    run_phase "mutation" mutation_suite
else
    status_skip "mutation" "set INKYPI_VALIDATE_MUTATION=1 to run narrow mutation validation"
fi

printf 'PASS %-10s %s\n' "summary" "pre-flash validation complete"
