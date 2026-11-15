#!/bin/bash

# This file is sourced from bash and from zsh (the macOS default shell).
# BASH_SOURCE is bash-only; zsh's equivalent is the %x prompt escape. Under
# zsh, BASH_SOURCE is empty, and REPO_ROOT used to resolve to the parent of
# the current directory.
if [ -n "${BASH_SOURCE[0]:-}" ]; then
    _inkypi_venv_sh="${BASH_SOURCE[0]}"
elif [ -n "${ZSH_VERSION:-}" ]; then
    eval '_inkypi_venv_sh="${(%):-%x}"'
else
    _inkypi_venv_sh="$0"
fi
REPO_ROOT="$(cd "$(dirname "$_inkypi_venv_sh")/.." && pwd)"
unset _inkypi_venv_sh
VENV_DIR="${REPO_ROOT}/.venv"
# pyproject.toml's requires-python; scripts/dev_environment.py has the same.
INKYPI_PYTHON_VERSION="3.13"
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
    # Exit appropriately whether sourced or executed
    if (return 0 2>/dev/null); then
        return 0
    else
        exit 0
    fi
fi

# True when the interpreter is the supported Python version. A bare python3
# is often a newer release (Homebrew's, for one), and a venv built from it
# installs a different set of wheels than CI and the Pi run.
inkypi_is_supported_python() {
    "$1" -c "import sys; sys.exit(sys.version_info[:2] != (${INKYPI_PYTHON_VERSION/./, }))" 2>/dev/null
}

# Prints the first interpreter on PATH that is the supported version.
inkypi_find_python() {
    local candidate
    for candidate in "python${INKYPI_PYTHON_VERSION}" python3; do
        if command -v "$candidate" >/dev/null 2>&1 && inkypi_is_supported_python "$candidate"; then
            command -v "$candidate"
            return 0
        fi
    done
    return 1
}

if [ ! -d "$VENV_DIR" ]; then
    if ! INKYPI_PYTHON="$(inkypi_find_python)"; then
        echo "InkyPi needs Python ${INKYPI_PYTHON_VERSION}, and neither python${INKYPI_PYTHON_VERSION} nor python3 on PATH is that version." >&2
        echo "Install it (for example: brew install python@${INKYPI_PYTHON_VERSION}, or uv python install ${INKYPI_PYTHON_VERSION}) and run this again." >&2
        if (return 0 2>/dev/null); then return 1; else exit 1; fi
    fi
    echo "Creating virtual environment in $VENV_DIR with $INKYPI_PYTHON..."
    if ! "$INKYPI_PYTHON" -m venv "$VENV_DIR"; then
        echo "Failed to create virtual environment with $INKYPI_PYTHON." >&2
        if (return 0 2>/dev/null); then return 1; else exit 1; fi
    fi
fi

echo "Activating virtual environment..."
# shellcheck source=/dev/null
if ! source "$VENV_DIR/bin/activate"; then
    echo "Failed to activate virtual environment." >&2
    if (return 0 2>/dev/null); then return 1; else exit 1; fi
fi

# A venv made earlier, or by hand, may be on another Python. Its packages can
# still match the lock, so the drift check below would not notice.
if ! inkypi_is_supported_python python3; then
    echo "$VENV_DIR runs $(python3 --version 2>&1), but InkyPi needs Python ${INKYPI_PYTHON_VERSION}." >&2
    echo "Remove it (deactivate; rm -rf \"$VENV_DIR\") and source scripts/venv.sh again." >&2
    if (return 0 2>/dev/null); then return 1; else exit 1; fi
fi

if command -v python3 >/dev/null 2>&1; then
    PY_BIN=python3
else
    PY_BIN=python
fi

if ! "$PY_BIN" "${REPO_ROOT}/scripts/dev_environment.py"; then
    "$PY_BIN" "${REPO_ROOT}/scripts/dev_environment.py" --sync || return 1 2>/dev/null || exit 1
fi

setup_pythonpath

echo "Python virtual environment initialized, run 'deactivate' to exit"
