#!/bin/bash

VENV_DIR=".venv"
REQUIREMENTS_FILE="install/requirements-dev.txt"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}" 2>/dev/null)" && cd .. && pwd)"
SRC_DIR="src"
SRC_ABS="${REPO_ROOT}/${SRC_DIR}"

# Provide a python shim if python is missing but python3 exists
if ! command -v python >/dev/null 2>&1 && command -v python3 >/dev/null 2>&1; then
    python() { command python3 "$@"; }
fi

setup_pythonpath() {
    local entry
    # Order matters for tests: repo root then src (prepending builds reversed order)
    PYTHONPATH_ENTRIES=("$SRC_ABS" "$REPO_ROOT")
    for entry in "${PYTHONPATH_ENTRIES[@]}"; do
        case ":${PYTHONPATH:-}:" in
            *":${entry}:"*) ;;
            *)
                PYTHONPATH="${entry}${PYTHONPATH:+:$PYTHONPATH}"
                ;;
        esac
    done

    export PYTHONPATH
    export SRC_DIR=$SRC_DIR
}

if [ "${INKYPI_PYTHONPATH_ONLY:-}" = "1" ]; then
    setup_pythonpath
    # shellcheck disable=SC2310
    return 0 2>/dev/null || exit 0
fi

if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment in $VENV_DIR..."
    if ! python3 -m venv "$VENV_DIR"; then
        echo "Failed to create virtual environment. Ensure python3 is installed."
        exit 1
    fi
fi

echo "Activating virtual environment..."
# shellcheck source=/dev/null
if ! source "$VENV_DIR/bin/activate"; then
    echo "Failed to activate virtual environment."
    exit 1
fi

if command -v python3 >/dev/null 2>&1; then
    PY_BIN=python3
else
    PY_BIN=python
fi

$PY_BIN -m pip install --upgrade pip
$PY_BIN -m pip install --no-cache-dir -r "$REQUIREMENTS_FILE"

setup_pythonpath

echo "Python virtual environment initialized, run 'deactivate' to exit"
