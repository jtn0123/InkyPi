#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${SCRIPT_DIR}/.."
cd "${REPO_ROOT}"

source scripts/venv.sh

export INKYPI_ENV=dev
export INKYPI_NO_REFRESH=1
export PYTHONPATH="src:${PYTHONPATH:-}"

# Prefer a local, ignored device config to avoid touching tracked files
LOCAL_CFG="${REPO_ROOT}/src/config/device.local.json"
DEV_CFG="${REPO_ROOT}/src/config/device_dev.json"
PROD_CFG="${REPO_ROOT}/src/config/device.json"

if [ ! -f "$LOCAL_CFG" ]; then
  if [ -f "$DEV_CFG" ]; then
    cp "$DEV_CFG" "$LOCAL_CFG"
  elif [ -f "$PROD_CFG" ]; then
    cp "$PROD_CFG" "$LOCAL_CFG"
  else
    # As a last resort, create a minimal stub
    echo '{"name":"InkyPi Local","display_type":"mock","resolution":[800,480],"orientation":"horizontal","playlist_config":{"playlists":[],"active_playlist":""}}' > "$LOCAL_CFG"
  fi
fi

export INKYPI_CONFIG_FILE="$LOCAL_CFG"

python src/inkypi.py --dev --web-only "$@"


