#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${SCRIPT_DIR}/.."
cd "${REPO_ROOT}"

source scripts/venv.sh

# Lint with Ruff (imports, flakes, basic style)
ruff check src tests scripts

# Verify formatting with Black
black --check src tests scripts


