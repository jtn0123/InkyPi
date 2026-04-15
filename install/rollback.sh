#!/bin/bash
# rollback.sh — Revert InkyPi to the previous version recorded by do_update.sh.
#
# do_update.sh writes the outgoing semver tag to
#   /var/lib/inkypi/prev_version
# BEFORE running `git checkout` on the new target (JTN-673 / JTN-708), so even
# when an update bricks mid-way the breadcrumb is already on disk.  This script
# reads that file, validates the tag format, checks out the previous tag, and
# delegates to update.sh for dependency sync + service restart.
#
# Usage:
#   sudo bash rollback.sh
#
# Contract (matches do_update.sh / update.sh — JTN-600 / JTN-607 / JTN-704):
#   * set -euo pipefail is mandatory; any failure propagates.
#   * The EXIT trap in update.sh takes over once we exec it, so a failed
#     rollback still writes /var/lib/inkypi/.last-update-failure just like any
#     other failed update.
#   * INKYPI_LOCKFILE_DIR is honored so integration tests can redirect state
#     writes without touching the real /var/lib/inkypi.
#
# Exit codes:
#   0   — rollback started (execs update.sh which itself exits 0 on success).
#   10  — prev_version breadcrumb missing or empty (nothing to roll back to).
#   11  — prev_version contents failed the semver regex validation.
#   12  — previous tag not available in the local repo and cannot be fetched.
#   1   — generic failure (missing repo, missing update.sh, git errors, ...).

set -euo pipefail

# Resolve this script's directory (handles symlinks — mirrors do_update.sh).
SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do
  DIR=$( cd -P "$( dirname "$SOURCE" )" >/dev/null 2>&1 && pwd )
  SOURCE=$(readlink "$SOURCE")
  [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"
done
SCRIPT_DIR=$( cd -P "$( dirname "$SOURCE" )" >/dev/null 2>&1 && pwd )

# ---------------------------------------------------------------------------
# Resolve the git repo root (mirrors do_update.sh for consistency).
# ---------------------------------------------------------------------------
PROJECT_DIR="${PROJECT_DIR:-/usr/local/inkypi}"

if [ -L "$PROJECT_DIR/src" ] && REAL_SRC=$(realpath "$PROJECT_DIR/src" 2>/dev/null) && [ -n "$REAL_SRC" ]; then
  REPO_DIR=$(dirname "$REAL_SRC")
elif [ -d "$SCRIPT_DIR/../.git" ]; then
  REPO_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
else
  echo "ERROR: Cannot determine git repository root." >&2
  echo "  Checked: symlink $PROJECT_DIR/src and $SCRIPT_DIR/../.git" >&2
  exit 1
fi

if ! git -C "$REPO_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "ERROR: $REPO_DIR is not a git repository." >&2
  exit 1
fi

echo "Repository root: $REPO_DIR"

# ---------------------------------------------------------------------------
# Read the prev_version breadcrumb.
# ---------------------------------------------------------------------------
# JTN-704 parity: honor INKYPI_LOCKFILE_DIR so integration tests can redirect
# state writes to a tempdir without touching the real /var/lib/inkypi.
STATE_DIR="${INKYPI_LOCKFILE_DIR:-/var/lib/inkypi}"
PREV_VERSION_FILE="$STATE_DIR/prev_version"

if [ ! -f "$PREV_VERSION_FILE" ]; then
  echo "ERROR: No previous-version breadcrumb at $PREV_VERSION_FILE." >&2
  echo "  Nothing to roll back to — do_update.sh has not run on this host," >&2
  echo "  or the breadcrumb was cleared." >&2
  exit 10
fi

# Read and trim whitespace/newlines defensively.
PREV_TAG=$(tr -d '[:space:]' < "$PREV_VERSION_FILE")

if [ -z "$PREV_TAG" ]; then
  echo "ERROR: $PREV_VERSION_FILE is empty." >&2
  exit 10
fi

# Defense-in-depth: the same strict semver regex used by the Flask caller in
# src/blueprints/settings/__init__.py::_TAG_RE and by do_update.sh.  Matching
# the *bash* flavor here deliberately — keep this byte-for-byte aligned with
# do_update.sh's validator so an attacker cannot bypass validation by writing
# a crafted value into prev_version.
if ! [[ "$PREV_TAG" =~ ^v?[0-9]+\.[0-9]+\.[0-9]+(-[A-Za-z0-9.]+)?$ ]]; then
  echo "ERROR: prev_version contents failed semver validation: $PREV_TAG" >&2
  echo "  Refusing to check out an arbitrary revision." >&2
  exit 11
fi

echo "Previous version: $PREV_TAG"

# ---------------------------------------------------------------------------
# Ensure the tag is available locally; fetch it if needed.
# ---------------------------------------------------------------------------
if ! git -C "$REPO_DIR" rev-parse --verify --quiet "refs/tags/$PREV_TAG" >/dev/null; then
  echo "Tag $PREV_TAG not present locally — fetching from origin..."
  if ! git -C "$REPO_DIR" fetch origin "refs/tags/$PREV_TAG:refs/tags/$PREV_TAG" --no-tags 2>/dev/null; then
    # Fall back to a full tag fetch.
    git -C "$REPO_DIR" fetch origin --tags --prune || true
  fi
  if ! git -C "$REPO_DIR" rev-parse --verify --quiet "refs/tags/$PREV_TAG" >/dev/null; then
    echo "ERROR: Tag $PREV_TAG is not available locally and could not be fetched." >&2
    exit 12
  fi
fi

# ---------------------------------------------------------------------------
# Check out the previous tag.
# ---------------------------------------------------------------------------
echo "Rolling back to $PREV_TAG..."
# Trailing `--` makes it unambiguous that $PREV_TAG is a revision, not a
# pathspec.  Mirrors the pattern used in do_update.sh.
git -C "$REPO_DIR" checkout "refs/tags/$PREV_TAG" --

# ---------------------------------------------------------------------------
# Delegate to update.sh for deps, CSS build, and service restart.
#
# The EXIT trap installed by update.sh (JTN-704) takes over here, so any
# failure during the rollback is recorded in .last-update-failure just like a
# normal update failure.  The JTN-600 / JTN-607 disable-systemd contract is
# also inherited verbatim — rollback.sh does NOT need to duplicate it.
# ---------------------------------------------------------------------------
UPDATE_SCRIPT="$REPO_DIR/install/update.sh"
if [ ! -f "$UPDATE_SCRIPT" ]; then
  echo "ERROR: update.sh not found at $UPDATE_SCRIPT" >&2
  exit 1
fi

echo "Running update.sh from rolled-back code..."
exec bash "$UPDATE_SCRIPT"
