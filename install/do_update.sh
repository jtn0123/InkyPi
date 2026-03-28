#!/bin/bash
# do_update.sh — Pull latest code from git, then delegate to update.sh for
# dependency installation, CSS build, and service restart.
#
# Usage:
#   sudo bash do_update.sh [target_tag]
#
# If target_tag is omitted, checks out the latest semver tag.

set -euo pipefail

# Resolve this script's directory (handles symlinks)
SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do
  DIR=$( cd -P "$( dirname "$SOURCE" )" >/dev/null 2>&1 && pwd )
  SOURCE=$(readlink "$SOURCE")
  [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"
done
SCRIPT_DIR=$( cd -P "$( dirname "$SOURCE" )" >/dev/null 2>&1 && pwd )

# ---------------------------------------------------------------------------
# Resolve the git repo root
# ---------------------------------------------------------------------------
# In production, install.sh symlinks src/ → /usr/local/inkypi/src. Following
# the symlink back gives us the actual git checkout directory.
PROJECT_DIR="${PROJECT_DIR:-/usr/local/inkypi}"

if [ -L "$PROJECT_DIR/src" ] && REAL_SRC=$(realpath "$PROJECT_DIR/src" 2>/dev/null) && [ -n "$REAL_SRC" ]; then
  REPO_DIR=$(dirname "$REAL_SRC")
elif [ -d "$SCRIPT_DIR/../.git" ]; then
  # Developer environment — script lives inside the repo
  REPO_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
else
  echo "ERROR: Cannot determine git repository root." >&2
  echo "  Checked: symlink $PROJECT_DIR/src and $SCRIPT_DIR/../.git" >&2
  exit 1
fi

# Validate it's actually a git repo
if ! git -C "$REPO_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "ERROR: $REPO_DIR is not a git repository." >&2
  exit 1
fi

echo "Repository root: $REPO_DIR"

# ---------------------------------------------------------------------------
# Save current version for rollback breadcrumb
# ---------------------------------------------------------------------------
CURRENT_VERSION=$(git -C "$REPO_DIR" describe --tags --abbrev=0 2>/dev/null || echo "unknown")
echo "$CURRENT_VERSION" > /tmp/inkypi_prev_version
echo "Current version: $CURRENT_VERSION"

# ---------------------------------------------------------------------------
# Fetch latest from origin
# ---------------------------------------------------------------------------
echo "Fetching latest from origin..."
git -C "$REPO_DIR" fetch origin --tags --prune

# ---------------------------------------------------------------------------
# Determine target tag
# ---------------------------------------------------------------------------
TARGET_TAG="${1:-}"
if [ -z "$TARGET_TAG" ]; then
  # Find the latest semver tag (v1.2.3 format)
  TARGET_TAG=$(git -C "$REPO_DIR" tag --sort=-v:refname | grep -E '^v?[0-9]+\.[0-9]+\.[0-9]+$' | head -1)
  if [ -z "$TARGET_TAG" ]; then
    echo "ERROR: No semver tags found in repository." >&2
    exit 1
  fi
fi

echo "Target version: $TARGET_TAG"

# ---------------------------------------------------------------------------
# Checkout target
# ---------------------------------------------------------------------------
if [ "$CURRENT_VERSION" = "$TARGET_TAG" ]; then
  echo "Already at $TARGET_TAG — re-running update.sh for dependency sync."
else
  echo "Checking out $TARGET_TAG..."
  git -C "$REPO_DIR" checkout "$TARGET_TAG"
fi

# ---------------------------------------------------------------------------
# Delegate to update.sh for deps, CSS build, and service restart
# ---------------------------------------------------------------------------
UPDATE_SCRIPT="$SCRIPT_DIR/update.sh"
if [ ! -f "$UPDATE_SCRIPT" ]; then
  echo "ERROR: update.sh not found at $UPDATE_SCRIPT" >&2
  exit 1
fi

echo "Running update.sh..."
exec bash "$UPDATE_SCRIPT"
