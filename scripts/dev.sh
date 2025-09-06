#!/usr/bin/env bash
set -euo pipefail

# Ensure venv and install dev deps using existing helper
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${SCRIPT_DIR}/.."
cd "${REPO_ROOT}"

source scripts/venv.sh

export INKYPI_ENV=dev
export PYTHONPATH="src:${PYTHONPATH:-}"

python src/inkypi.py --dev "$@"


