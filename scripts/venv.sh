#!/bin/bash

VENV_DIR=".venv"
REQUIREMENTS_FILE="install/requirements-dev.txt"
SRC_DIR="src"

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

python -m pip install --upgrade pip
python -m pip install --no-cache-dir -r "$REQUIREMENTS_FILE"

export PYTHONPATH="$SRC_DIR${PYTHONPATH:+:$PYTHONPATH}"
export SRC_DIR="$SRC_DIR"

echo "Python virtual environment initialized, run 'deactivate' to exit"
