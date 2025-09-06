#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${SCRIPT_DIR}/.."
cd "${REPO_ROOT}"

source scripts/venv.sh

# Auto-fix with Ruff (imports and safe fixes), then format with Black
ruff check --fix src tests scripts
black src tests scripts


