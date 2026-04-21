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
# JTN-787: EXIT trap to record failures that happen *before* delegation to
# install/update.sh. Without this, errors in the git fetch/checkout phase
# (e.g. a dirty working tree blocking `git checkout`) abort do_update.sh
# before it exec's update.sh, so update.sh's JTN-704 trap never runs and
# the UI has zero signal about why the update failed.
#
# The JSON shape MUST match update.sh's trap exactly so downstream readers
# (src/blueprints/settings/_update_status.py::read_last_update_failure)
# don't need to branch on origin. Required keys: timestamp, exit_code,
# last_command, recent_journal_lines.
#
# LOCKFILE_DIR is overridable via INKYPI_LOCKFILE_DIR for tests — same
# contract as install/update.sh (JTN-704).
# ---------------------------------------------------------------------------
LOCKFILE_DIR="/var/lib/inkypi"
if [ -n "${INKYPI_LOCKFILE_DIR:-}" ]; then
  LOCKFILE_DIR="$INKYPI_LOCKFILE_DIR"
fi
FAILURE_FILE="$LOCKFILE_DIR/.last-update-failure"

# Track last command description so the trap can report which phase failed.
_current_step="startup"

_inkypi_do_update_exit_trap() {
  local rc=$?
  # Only act on non-zero exits; a successful do_update.sh exec's update.sh
  # whose own trap takes over. If we return 0 here without exec'ing (e.g.
  # same-version early continue followed by the exec), this branch is never
  # reached because `exec` replaces the process.
  if [ "$rc" -eq 0 ]; then
    return 0
  fi
  local ts
  ts=$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo "unknown")
  # Best-effort journal tail — same pattern as update.sh so the UI sees
  # identical fields on either code path.
  local journal_tail=""
  if command -v journalctl >/dev/null 2>&1; then
    # Prefer the transient unit name exported by systemd-run, if present.
    local unit_for_journal="${INVOCATION_ID:+inkypi-update}"
    [ -z "$unit_for_journal" ] && unit_for_journal="inkypi-update"
    journal_tail=$(journalctl -u "$unit_for_journal" -n 20 --no-pager 2>/dev/null \
      | tail -n 20 || true)
  fi
  local journal_json
  if command -v python3 >/dev/null 2>&1; then
    journal_json=$(python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))' \
      <<<"$journal_tail" 2>/dev/null || echo '""')
  else
    journal_json='"'$(printf '%s' "$journal_tail" \
      | tr -d '\r' \
      | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e ':a;N;$!ba;s/\n/\\n/g' \
      | tr -d '\000-\010\013\014\016-\037')'"'
  fi
  local step_json
  if command -v python3 >/dev/null 2>&1; then
    step_json=$(python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().rstrip("\n")))' \
      <<<"$_current_step" 2>/dev/null || echo '""')
  else
    step_json='"'$(printf '%s' "$_current_step" \
      | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g')'"'
  fi
  mkdir -p "$LOCKFILE_DIR" 2>/dev/null || true
  local tmp="${FAILURE_FILE}.tmp"
  {
    printf '{'
    printf '"timestamp":"%s",' "$ts"
    printf '"exit_code":%d,' "$rc"
    printf '"last_command":%s,' "$step_json"
    printf '"recent_journal_lines":%s' "$journal_json"
    printf '}\n'
  } > "$tmp" 2>/dev/null || true
  if [ -s "$tmp" ]; then
    mv -f "$tmp" "$FAILURE_FILE" 2>/dev/null || rm -f "$tmp" 2>/dev/null || true
  else
    rm -f "$tmp" 2>/dev/null || true
  fi
}
trap _inkypi_do_update_exit_trap EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

# ---------------------------------------------------------------------------
# Resolve the git repo root
# ---------------------------------------------------------------------------
# In production, install.sh symlinks src/ → /usr/local/inkypi/src. Following
# the symlink back gives us the actual git checkout directory.
PROJECT_DIR="${PROJECT_DIR:-/usr/local/inkypi}"

_current_step="resolve_repo_dir"
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

# JTN-K2: All `git -C "$REPO_DIR"` invocations below go through this wrapper
# so ``safe.directory='*'`` is set on every git call.  do_update.sh runs as
# root via ``systemd-run`` (see _start_update_via_systemd), but on dev
# installs the repo at /home/$user/InkyPi is owned by a non-root user.
# Without ``safe.directory``, git refuses with "dubious ownership"
# (CVE-2022-24765) and the ``rev-parse`` below silently fails, which the
# error message renders as "not a git repository" — no signal to the user
# that the real problem was repo ownership.  Mirrors the same workaround
# install.sh already applies on its preflight checks.
git_repo() {
  git -c safe.directory="*" -C "$REPO_DIR" "$@"
}

# Validate it's actually a git repo
_current_step="validate_git_repo"
if ! git_repo rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "ERROR: $REPO_DIR is not a git repository." >&2
  exit 1
fi

echo "Repository root: $REPO_DIR"

# ---------------------------------------------------------------------------
# Save current version for rollback breadcrumb
# ---------------------------------------------------------------------------
CURRENT_VERSION=$(git_repo describe --tags --abbrev=0 2>/dev/null || echo "unknown")
# JTN-787: honour INKYPI_LOCKFILE_DIR so tests can redirect state writes
# without needing write access to /var/lib. Production callers do not set it.
# Failure to create the state dir (e.g. running as non-root on a fresh box)
# is non-fatal — the prev_version breadcrumb is best-effort and its absence
# only disables the rollback button, it does not block the update itself.
STATE_DIR="${INKYPI_LOCKFILE_DIR:-/var/lib/inkypi}"
if mkdir -p "$STATE_DIR" 2>/dev/null; then
  echo "$CURRENT_VERSION" > "$STATE_DIR/prev_version" 2>/dev/null || true
else
  echo "Warning: could not create $STATE_DIR; skipping prev_version breadcrumb." >&2
fi
echo "Current version: $CURRENT_VERSION"

# ---------------------------------------------------------------------------
# JTN-673: Ensure the origin remote has a full branch refspec before fetching.
# Older installers pinned origin to a single-tag refspec such as
#   +refs/tags/v0.28.1:refs/tags/v0.28.1
# which causes `git fetch origin` to download only that one tag.  As a
# result, `git branch -r` is empty, and `git checkout refs/tags/<new_tag>`
# still works but leaves HEAD detached with no remote-tracking branches —
# meaning the next do_update.sh run cannot re-resolve the latest semver tag
# from `git tag --sort=-v:refname` after a fresh fetch of only the old tag.
# More visibly: if any code path falls back to `git checkout main` it will
# fail with "'origin/main' is not a commit".
#
# Fix: if the full branch glob is not already in the fetch refspec list, wipe
# and re-add it so subsequent fetches download all branches.
# ---------------------------------------------------------------------------
if ! git_repo config --get-all remote.origin.fetch 2>/dev/null \
    | grep -qF '+refs/heads/*:refs/remotes/origin/*'; then
  echo "Widening narrow git fetch refspec to include all branches..."
  git_repo config --unset-all remote.origin.fetch || true
  git_repo config --add remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'
fi

# ---------------------------------------------------------------------------
# Fetch latest from origin
# ---------------------------------------------------------------------------
_current_step="git_fetch"
echo "Fetching latest from origin..."
git_repo fetch origin --tags --prune

# ---------------------------------------------------------------------------
# Determine target tag
# ---------------------------------------------------------------------------
TARGET_TAG="${1:-}"
if [ -z "$TARGET_TAG" ]; then
  # Find the latest semver tag (v1.2.3 format)
  TARGET_TAG=$(git_repo tag --sort=-v:refname | grep -E '^v?[0-9]+\.[0-9]+\.[0-9]+$' | head -1)
  if [ -z "$TARGET_TAG" ]; then
    echo "ERROR: No semver tags found in repository." >&2
    exit 1
  fi
fi

# Defense-in-depth: validate the tag format even though the Flask caller
# (src/blueprints/settings/__init__.py::_start_update_via_systemd) already
# enforces a strict semver regex before exec. See JTN-319.
if ! [[ "$TARGET_TAG" =~ ^v?[0-9]+\.[0-9]+\.[0-9]+(-[A-Za-z0-9.]+)?$ ]]; then
  echo "ERROR: Invalid target tag format: $TARGET_TAG" >&2
  exit 1
fi

echo "Target version: $TARGET_TAG"

# ---------------------------------------------------------------------------
# Checkout target
# ---------------------------------------------------------------------------
if [ "$CURRENT_VERSION" = "$TARGET_TAG" ]; then
  echo "Already at $TARGET_TAG — re-running update.sh for dependency sync."
else
  # JTN-787: Reset the narrow allowlist of generated build artifacts before
  # checkout so a dirty working tree cannot abort the update with
  # "Your local changes to the following files would be overwritten by
  # checkout". The CSS bundle is rebuilt by update.sh (build_css_bundle)
  # immediately after this exec, so discarding it here is safe.
  #
  # Keep this allowlist to exactly one known-generated path — do NOT expand
  # it, because every additional path is a chance to silently throw away
  # legitimate user changes.
  _current_step="reset_generated_artifacts"
  git_repo checkout -- src/static/styles/main.css 2>/dev/null || true

  # JTN-K2: On dev installs the repo at /home/$user/InkyPi may have
  # additional tracked-file modifications beyond the narrow CSS reset
  # above (local debugging edits, work-in-progress fixes, etc.). Without
  # this stash, the checkout below aborts with "Your local changes
  # would be overwritten by checkout" and the update silently fails.
  #
  # Tracked-only — do NOT pass --include-untracked, which would stash
  # the runtime ``src/config/device.json`` that the live service reads.
  # Stashed entries remain in ``git stash list`` so the user can recover
  # via ``git stash pop`` after the update.  No-op if the tree is clean.
  _current_step="stash_local_modifications"
  if ! git_repo diff --quiet; then
    echo "Stashing local modifications before checkout (recover with 'git stash pop')..."
    git_repo stash push --message "auto-stash by do_update.sh $(date -u +%Y-%m-%dT%H:%M:%SZ)" --quiet || true
  fi

  _current_step="git_checkout"
  echo "Checking out $TARGET_TAG..."
  # Pass the tag via an explicit revision argument before ``--`` so it
  # cannot be interpreted as a flag by git checkout, and add a trailing
  # ``--`` to make clear nothing after it is a pathspec.
  git_repo checkout "refs/tags/$TARGET_TAG" --
fi

# ---------------------------------------------------------------------------
# Delegate to update.sh for deps, CSS build, and service restart
# ---------------------------------------------------------------------------
UPDATE_SCRIPT="$REPO_DIR/install/update.sh"
if [ ! -f "$UPDATE_SCRIPT" ]; then
  echo "ERROR: update.sh not found at $UPDATE_SCRIPT" >&2
  exit 1
fi

_current_step="exec_update_sh"
echo "Running update.sh from checked-out code..."
exec bash "$UPDATE_SCRIPT"
