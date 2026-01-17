#!/usr/bin/env bash

VENV_DIR="${VENV_DIR:-.venv}"
REQUIREMENTS_FILE="install/requirements-dev.txt"
SRC_DIR="$(realpath src)"

if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment in $VENV_DIR..."
    if ! python3 -m venv "$VENV_DIR"; then
        echo "Failed to create virtual environment. Ensure python3 is installed."
        exit 1
    fi
fi

echo "Activating virtual environment..."
source $VENV_DIR/bin/activate

if [ -z "$VIRTUAL_ENV" ]; then
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
