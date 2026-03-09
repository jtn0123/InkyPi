#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${SCRIPT_DIR}/.."
cd "${REPO_ROOT}" || exit

# Use the active virtualenv when provided. Otherwise activate an existing repo
# venv directly so test runs do not reinstall dependencies on each invocation.
if [[ -z "${VIRTUAL_ENV:-}" ]]; then
    if [[ -f ".venv/bin/activate" ]]; then
        # shellcheck source=/dev/null
        source ".venv/bin/activate"
    else
        # shellcheck source=scripts/venv.sh
        source scripts/venv.sh
    fi
fi

export PYTHONPATH="src${PYTHONPATH:+:$PYTHONPATH}"

BROWSER_TEST_TARGETS=(
    tests/integration/test_browser_smoke.py
    tests/integration/test_e2e_form_workflows.py
    tests/integration/test_more_a11y.py
    tests/integration/test_playlist_a11y.py
    tests/integration/test_playlist_interactions.py
    tests/integration/test_plugin_add_to_playlist_ui.py
    tests/integration/test_weather_autofill.py
    tests/integration/test_weather_image_render.py
)

PLUGIN_A_TARGETS=(
    tests/plugins/test_weather.py
    tests/plugins/test_calendar.py
    tests/plugins/test_wpotd.py
)

PLUGIN_B_TARGETS=(
    tests/plugins/test_clock.py
    tests/plugins/test_ai_image.py
    tests/plugins/test_unsplash.py
    tests/plugins/test_github_plugins.py
    tests/plugins/test_apod.py
)

is_truthy() {
    case "${1:-}" in
        1|true|TRUE|yes|YES)
            return 0
            ;;
    esac
    return 1
}

is_browser_target() {
    local target="$1"
    local browser_target
    for browser_target in "${BROWSER_TEST_TARGETS[@]}"; do
        if [[ "${target}" == "${browser_target}" ]]; then
            return 0
        fi
    done
    return 1
}

is_in_array() {
    local needle="$1"
    shift

    local item
    for item in "$@"; do
        if [[ "${needle}" == "${item}" ]]; then
            return 0
        fi
    done
    return 1
}

run_pytest() {
    local worker_count="$1"
    shift

    if [[ "${worker_count}" -le 1 ]]; then
        python -m pytest -q "$@"
    else
        python -m pytest -n "${worker_count}" --dist=loadfile -q "$@"
    fi
}

build_plugin_c_targets() {
    local target
    for target in tests/plugins/test_*.py; do
        [[ -e "${target}" ]] || continue
        if is_in_array "${target}" "${PLUGIN_A_TARGETS[@]}"; then
            continue
        fi
        if is_in_array "${target}" "${PLUGIN_B_TARGETS[@]}"; then
            continue
        fi
        printf '%s\n' "${target}"
    done
}

LANE_LOG_DIR=""
LANE_PIDS=()
LANE_NAMES=()
LANE_LOGS=()

cleanup_lane_logs() {
    if [[ -n "${LANE_LOG_DIR}" && -d "${LANE_LOG_DIR}" ]]; then
        rm -rf "${LANE_LOG_DIR}"
    fi
}

launch_lane() {
    local lane_name="$1"
    local worker_count="$2"
    shift 2

    local log_path="${LANE_LOG_DIR}/${lane_name}.log"
    printf 'Launching %s lane with %s worker(s)\n' "${lane_name}" "${worker_count}"
    (
        printf 'Lane: %s\n' "${lane_name}"
        printf 'Workers: %s\n\n' "${worker_count}"
        run_pytest "${worker_count}" "$@"
    ) >"${log_path}" 2>&1 &

    LANE_PIDS+=("$!")
    LANE_NAMES+=("${lane_name}")
    LANE_LOGS+=("${log_path}")
}

run_sharded_no_arg_suite() {
    local lane_workers="${PYTEST_LANE_WORKERS:-2}"
    local core_target
    local -a core_args=(
        tests/static
        tests/test_model.py
        tests/unit
        tests/integration
    )
    local -a plugin_c_targets=()
    local status=0
    local index

    for core_target in "${BROWSER_TEST_TARGETS[@]}"; do
        core_args+=("--ignore=${core_target}")
    done

    while IFS= read -r core_target; do
        [[ -n "${core_target}" ]] || continue
        plugin_c_targets+=("${core_target}")
    done < <(build_plugin_c_targets)

    export SKIP_UI=1
    export SKIP_A11Y=1

    LANE_LOG_DIR="$(mktemp -d "${TMPDIR:-/tmp}/inkypi-tests.XXXXXX")"
    trap cleanup_lane_logs EXIT

    printf 'Running sharded local suite with lane worker count %s\n' "${lane_workers}"
    launch_lane core "${lane_workers}" "${core_args[@]}"
    launch_lane plugins-a "${lane_workers}" "${PLUGIN_A_TARGETS[@]}"
    launch_lane plugins-b "${lane_workers}" "${PLUGIN_B_TARGETS[@]}"
    launch_lane plugins-c "${lane_workers}" "${plugin_c_targets[@]}"

    for index in "${!LANE_PIDS[@]}"; do
        if wait "${LANE_PIDS[${index}]}"; then
            printf '%s lane passed\n' "${LANE_NAMES[${index}]}"
        else
            status=1
            printf '%s lane failed\n' "${LANE_NAMES[${index}]}" >&2
            cat "${LANE_LOGS[${index}]}" >&2
        fi
    done

    return "${status}"
}

target_count=0
file_target_count=0
run_browser_tests=0

for arg in "$@"; do
    if [[ "$arg" == -* ]]; then
        continue
    fi

    target="${arg%%::*}"
    if [[ ! -e "$target" && "$arg" != *"::"* ]]; then
        continue
    fi

    ((target_count += 1))
    if [[ -f "$target" ]]; then
        ((file_target_count += 1))
    fi
    if is_browser_target "$target"; then
        run_browser_tests=1
    fi
done

if is_truthy "${REQUIRE_BROWSER_SMOKE:-}"; then
    run_browser_tests=1
fi

if [[ "${run_browser_tests}" -eq 0 ]]; then
    export SKIP_UI="${SKIP_UI:-1}"
    export SKIP_A11Y="${SKIP_A11Y:-1}"
fi

if [[ "$#" -eq 0 ]]; then
    run_sharded_no_arg_suite
elif [[ "${target_count}" -eq 1 && "${file_target_count}" -eq 1 ]]; then
    python -m pytest -q "$@"
else
    # Keep each file on a single worker to reduce cross-test interference.
    run_pytest "${PYTEST_WORKERS:-4}" "$@"
fi
