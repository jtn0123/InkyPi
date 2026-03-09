#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${SCRIPT_DIR}/.."
cd "${REPO_ROOT}" || exit

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
export SKIP_UI="${SKIP_UI:-1}"
export SKIP_A11Y="${SKIP_A11Y:-1}"

if [[ "$#" -gt 0 ]]; then
    python -m pytest -q --durations="${PYTEST_DURATIONS:-25}" "$@"
else
    python -m pytest -q --durations="${PYTEST_DURATIONS:-25}" tests/plugins
fi
