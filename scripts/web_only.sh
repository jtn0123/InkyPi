#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${SCRIPT_DIR}/.."
cd "${REPO_ROOT}"

source scripts/venv.sh

export INKYPI_ENV=dev
export INKYPI_NO_REFRESH=1
export PYTHONPATH="src:${PYTHONPATH:-}"

python src/inkypi.py --dev --web-only "$@"


