#!/usr/bin/env bash

set -Eeuo pipefail

APPNAME="inkypi"
SERVICE="$APPNAME.service"

BRANCH="main"
HARD_RESET=0
VERBOSE=0

SCRIPT_DIR=$(cd -P "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)
REPO_DIR=$(cd "$SCRIPT_DIR/.." && pwd)

log() { echo -e "[dev-update] $*"; }

usage() {
  cat <<USAGE
Usage: $(basename "$0") [-b <branch>] [-r] [-v]

Options:
  -b <branch>   Target git branch to update (default: main)
  -r            Force hard reset to origin/<branch> (discard local changes)
  -v            Verbose output

Behavior:
  - Stops $SERVICE if running
  - git fetch + (pull --rebase or hard reset)
  - Runs install/update.sh to update deps and restart service
  - Shows service status and recent logs
USAGE
}

while getopts ":b:rvh" opt; do
  case "$opt" in
    b) BRANCH="$OPTARG" ;;
    r) HARD_RESET=1 ;;
    v) VERBOSE=1 ;;
    h) usage; exit 0 ;;
    :) log "Option -$OPTARG requires an argument"; usage; exit 1 ;;
    \?) log "Invalid option: -$OPTARG"; usage; exit 1 ;;
  esac
done

# Detect repo root if executed from elsewhere
if git -C "$REPO_DIR" rev-parse --show-toplevel >/dev/null 2>&1; then
  REPO_DIR=$(git -C "$REPO_DIR" rev-parse --show-toplevel)
else
  log "Error: Cannot locate git repository from $REPO_DIR"; exit 1
fi

on_error() {
  local line="$1"
  log "ERROR on line $line"
  log "Attempting to restore service state..."
  if [[ "${WAS_ACTIVE:-0}" -eq 1 ]]; then
    sudo systemctl start "$SERVICE" || true
  fi
}
trap 'on_error $LINENO' ERR

log "Repository: $REPO_DIR"
log "Branch: $BRANCH | Hard reset: $HARD_RESET | Verbose: $VERBOSE"

# Remember current service state
if /usr/bin/systemctl is-active --quiet "$SERVICE"; then
  WAS_ACTIVE=1
  log "Stopping $SERVICE"
  sudo systemctl stop "$SERVICE"
else
  WAS_ACTIVE=0
  log "$SERVICE not running"
fi

log "Updating git repository"
cd "$REPO_DIR"
git fetch origin --prune ${VERBOSE:+--verbose}

# Ensure we are on the target branch
git checkout "$BRANCH" ${VERBOSE:+--progress}

if [[ "$HARD_RESET" -eq 1 ]]; then
  log "Hard resetting to origin/$BRANCH"
  git reset --hard "origin/$BRANCH"
else
  log "Pulling latest changes (rebase, autostash)"
  git pull --rebase --autostash origin "$BRANCH"
fi

# Optional: update submodules if present
if [ -f .gitmodules ]; then
  log "Updating submodules"
  git submodule update --init --recursive ${VERBOSE:+--progress}
fi

log "Running installer update script"
sudo bash "$REPO_DIR/install/update.sh"

log "Checking service status"
systemctl status "$SERVICE" --no-pager || true

log "Recent service logs"
journalctl -u "$SERVICE" -n 80 --no-pager || true

log "Done."



