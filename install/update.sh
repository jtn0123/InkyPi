#!/bin/bash

SOURCE=${BASH_SOURCE[0]}
while [ -h "$SOURCE" ]; do # resolve $SOURCE until the file is no longer a symlink
  DIR=$( cd -P "$( dirname "$SOURCE" )" >/dev/null 2>&1 && pwd )
  SOURCE=$(readlink "$SOURCE")
  [[ $SOURCE != /* ]] && SOURCE=$DIR/$SOURCE
done
SCRIPT_DIR=$( cd -P "$( dirname "$SOURCE" )" >/dev/null 2>&1 && pwd )

APPNAME="inkypi"
INSTALL_PATH="/usr/local/$APPNAME"
BINPATH="/usr/local/bin"
VENV_PATH="$INSTALL_PATH/venv_$APPNAME"

# JTN-666 / JTN-704: Defense-in-depth for JTN-600 parity. While update.sh is
# running, create /var/lib/inkypi/.install-in-progress. inkypi.service's
# ExecStartPre refuses to start if this file exists, so even if someone
# manually runs `systemctl start inkypi.service` or systemd tries to
# auto-restart, the service cannot thrash the Pi mid-update.
#
# JTN-704: The lockfile is cleared unconditionally by the EXIT trap (whether
# the update succeeds, errors, is killed, or Ctrl-C'd) so a failed update no
# longer leaves the service permanently disabled. On failure exit, structured
# failure metadata is written to .last-update-failure for later inspection
# (UI surfacing, diagnostics, rollback).
# JTN-704: LOCKFILE_DIR is overridable via env so the failure-recovery
# integration test can redirect state writes to a tempdir without touching the
# real /var/lib/inkypi. Production callers (install.sh, do_update.sh, the
# systemd-run invocation in settings) do NOT set this var, so behavior is
# unchanged in production.
LOCKFILE_DIR="/var/lib/inkypi"
# JTN-704: allow the integration test to redirect state writes without
# touching the real /var/lib/inkypi. Production callers do not set this.
if [ -n "${INKYPI_LOCKFILE_DIR:-}" ]; then
  LOCKFILE_DIR="$INKYPI_LOCKFILE_DIR"
fi
LOCKFILE="$LOCKFILE_DIR/.install-in-progress"
FAILURE_FILE="$LOCKFILE_DIR/.last-update-failure"

SERVICE_FILE="$APPNAME.service"
SERVICE_FILE_SOURCE="$SCRIPT_DIR/$SERVICE_FILE"
SERVICE_FILE_TARGET="/etc/systemd/system/$SERVICE_FILE"

APT_REQUIREMENTS_FILE="$SCRIPT_DIR/debian-requirements.txt"
PIP_REQUIREMENTS_FILE="$SCRIPT_DIR/requirements.txt"

# JTN-669/674: Source shared helpers (formatting, stop_service, zramswap,
# earlyoom, get_os_version, build_css_bundle, fetch_wheelhouse, cleanup_wheelhouse)
# so install.sh and update.sh share a single source of truth.
# shellcheck source=install/_common.sh
source "$SCRIPT_DIR/_common.sh"

update_app_service() {
  echo "Updating $APPNAME systemd service."
  if [ -f "$SERVICE_FILE_SOURCE" ]; then
    sudo cp "$SERVICE_FILE_SOURCE" "$SERVICE_FILE_TARGET"
    # JTN-686: Also refresh inkypi-failure.service so the OnFailure= directive
    # in inkypi.service never dangles on pre-JTN-671 installs that are updating.
    install_failure_service_unit
    sudo systemctl daemon-reload
    sudo systemctl enable "$SERVICE_FILE"
    echo "Starting $APPNAME service."
    sudo systemctl start "$SERVICE_FILE"
    # JTN-684 / JTN-706: Explicitly verify the service reached active state.
    # systemctl start exits 0 even when the service subsequently fails
    # (e.g. ExecStart returns non-zero), so we wait for is-active with a
    # bounded timeout.
    #
    # JTN-706: The previous implementation used a 3-attempt retry loop with
    # sleep 1, which capped the total wait at 3 seconds. On a Pi Zero 2 W,
    # inkypi routinely takes 5-8 seconds to become active (flask import +
    # plugin discovery), so updates reported false failures on healthy
    # devices. We now poll up to 45 seconds via `timeout`, and distinguish
    # the two error modes: a genuinely-failed service (systemctl reports
    # `failed`) versus slow startup that exceeded the wait window.
    local wait_seconds=45
    if ! sudo timeout "$wait_seconds" bash -c \
        "until systemctl is-active --quiet \"$SERVICE_FILE\"; do sleep 1; done"; then
      if sudo systemctl is-failed --quiet "$SERVICE_FILE"; then
        echo_error "ERROR: $SERVICE_FILE failed to start (systemd reports failed state)."
      else
        echo_error "ERROR: Timed out waiting for $SERVICE_FILE to become active after ${wait_seconds}s."
      fi
      echo "Service status:" >&2
      sudo systemctl status --no-pager "$SERVICE_FILE" >&2 || true
      sudo systemctl show -p ActiveState,SubState,Result "$SERVICE_FILE" >&2 || true
      echo "Last 20 journal lines:" >&2
      sudo journalctl -u "$APPNAME" -n 20 --no-pager >&2 || true
      exit 1
    fi
  else
    echo_error "ERROR: Service file $SERVICE_FILE_SOURCE not found!"
    exit 1
  fi
}

update_cli() {
  rm -rf "$INSTALL_PATH/cli"
  mkdir -p "$INSTALL_PATH/cli"
  cp -a "$SCRIPT_DIR/cli/." "$INSTALL_PATH/cli/"
  sudo chmod +x "$INSTALL_PATH/cli/"*
}

# Ensure script is run with sudo. JTN-704: when the test-only env hook is
# set we skip the root check so the trap can be exercised from pytest without
# running the test suite as root; behavior is unchanged in production where
# INKYPI_UPDATE_TEST_FAIL_AT is never set.
if [ -z "${INKYPI_UPDATE_TEST_FAIL_AT:-}" ] \
   && [ -z "${INKYPI_UPDATE_TEST_EXIT_AFTER_TRAP:-}" ] \
   && [ "$EUID" -ne 0 ]; then
  echo_error "ERROR: This script requires root privileges. Please run it with sudo."
  exit 1
fi

# JTN-666 / JTN-704: Create the install-in-progress lockfile. inkypi.service's
# ExecStartPre refuses to start while this file exists (defense-in-depth for
# JTN-600's systemctl disable).
mkdir -p "$LOCKFILE_DIR"
touch "$LOCKFILE"

# JTN-704: Track the most recent command-line description so the EXIT trap can
# record *which step* failed in the structured failure record. Each top-level
# phase sets _current_step before the work begins.
_current_step="startup"

# JTN-704: Unconditional cleanup trap.
#
# On EVERY exit (success, explicit exit N, errexit, SIGINT, SIGTERM, SIGHUP),
# remove the lockfile so the service is never left permanently blocked by a
# stale /var/lib/inkypi/.install-in-progress. When the exit code is non-zero
# we also write a structured failure record to .last-update-failure so the UI
# / diagnostics can surface *why* the update failed (pip failure, CSS build,
# OOM, etc.) instead of relying on the system journal. On a successful exit
# we clear the stale .last-update-failure so downstream consumers see a clean
# signal.
#
# The trap fires via EXIT for `exit N` and errexit paths. We additionally
# install it on INT/TERM/HUP so Ctrl-C and systemd-stop during the update
# still clear the lockfile cleanly.
_inkypi_update_exit_trap() {
  local rc=$?
  # Remove lockfile first — this is the load-bearing invariant (JTN-704).
  rm -f "$LOCKFILE" 2>/dev/null || true
  if [ "$rc" -ne 0 ]; then
    # Non-zero exit: persist failure metadata for UI / diagnostics.
    local ts
    ts=$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo "unknown")
    local journal_tail=""
    if command -v journalctl >/dev/null 2>&1; then
      # Capture last 20 lines of inkypi-update journal if available; never fail
      # the trap because of this best-effort read.
      journal_tail=$(journalctl -u inkypi-update -n 20 --no-pager 2>/dev/null \
        | tail -n 20 || true)
    fi
    # Escape for embedding in a JSON string (backslash, dquote, control chars).
    # Use python3 when available for correctness; fall back to a conservative
    # sed transform when python3 is absent (target: minimal Pi OS environments).
    local journal_json
    if command -v python3 >/dev/null 2>&1; then
      journal_json=$(python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))' \
        <<<"$journal_tail" 2>/dev/null || echo '""')
    else
      # Strip CR, escape backslash + dquote, drop non-printables. Wrap in quotes.
      journal_json='"'$(printf '%s' "$journal_tail" \
        | tr -d '\r' \
        | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e ':a;N;$!ba;s/\n/\\n/g' \
        | tr -d '\000-\010\013\014\016-\037')'"'
    fi
    # Escape _current_step the same way (may contain spaces / quotes).
    local step_json
    if command -v python3 >/dev/null 2>&1; then
      step_json=$(python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().rstrip("\n")))' \
        <<<"$_current_step" 2>/dev/null || echo '""')
    else
      step_json='"'$(printf '%s' "$_current_step" \
        | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g')'"'
    fi
    mkdir -p "$LOCKFILE_DIR" 2>/dev/null || true
    # Write atomically via tmpfile + mv so a partial write never leaves the
    # consumer parsing half a JSON object.
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
  else
    # Success: remove any stale failure record from a previous aborted run.
    rm -f "$FAILURE_FILE" 2>/dev/null || true
  fi
}
trap _inkypi_update_exit_trap EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

# JTN-704: Test-only failure injection hook. Production behavior is unchanged
# unless INKYPI_UPDATE_TEST_FAIL_AT is set. The integration test sets this env
# var to simulate a mid-update failure and assert the trap writes a correct
# .last-update-failure record and removes the lockfile.
_inkypi_maybe_inject_failure() {
  local step="$1"
  if [ -n "${INKYPI_UPDATE_TEST_FAIL_AT:-}" ] && [ "$step" = "$INKYPI_UPDATE_TEST_FAIL_AT" ]; then
    _current_step="$step"
    echo "TEST: injecting failure at step '$step'" >&2
    exit 97
  fi
}
_inkypi_maybe_inject_failure "startup"

# JTN-704: Test-only success simulation. When set, exit 0 immediately after
# trap setup so the integration test can verify the success-path trap branch
# (no .last-update-failure written, lockfile removed). Production callers do
# not set this variable.
if [ -n "${INKYPI_UPDATE_TEST_EXIT_AFTER_TRAP:-}" ]; then
  exit 0
fi

# JTN-666: Stop and disable the service BEFORE touching files or venv so
# systemd cannot restart a half-installed service and thrash the Pi.
_current_step="stop_service"
_inkypi_maybe_inject_failure "stop_service"
stop_service

_current_step="apt_install"
_inkypi_maybe_inject_failure "apt_install"
apt-get update -y > /dev/null &
if [ -f "$APT_REQUIREMENTS_FILE" ]; then
  echo "Installing system dependencies... "
  if ! xargs -a "$APT_REQUIREMENTS_FILE" sudo apt-get install -y > /dev/null; then
    echo_error "ERROR: apt-get install failed — aborting update."
    exit 1
  fi
  echo_success "Installed system dependencies."
else
  echo_error "ERROR: System dependencies file $APT_REQUIREMENTS_FILE not found!"
  exit 1
fi

# Setup zramswap on any modern Pi OS that ships zram-tools (Bullseye/Bookworm/Trixie).
# This is critical on low-RAM boards like the Pi Zero 2 W (512 MB) — without
# zramswap, pip install of numpy/Pillow/playwright will OOM during the update step.
os_version=$(get_os_version)
if [[ "$os_version" =~ ^(11|12|13)$ ]] ; then
  echo "OS version is $os_version (Bullseye/Bookworm/Trixie) - setting up zramswap"
  setup_zramswap_service
else
  echo "OS version is $os_version - skipping zramswap setup (zram-tools not available on this release)."
fi
setup_earlyoom_service

_current_step="venv_check"
# Check if virtual environment exists
if [ ! -d "$VENV_PATH" ]; then
  echo_error "ERROR: Virtual environment not found at $VENV_PATH. Run the installation script first."
  exit 1
fi

# JTN-668: /tmp on Pi OS Trixie is a 213 MB tmpfs — too small for numpy's
# intermediate build artefacts (>500 MB). Redirect pip's build temp dir to
# /var/tmp which is disk-backed and has gigabytes free.  This is set before
# every pip invocation so it applies to pip upgrade as well as dependency
# install.  The directory is created with root ownership (script runs as root
# via sudo) and cleaned up after the install completes.
PIP_BUILD_TMPDIR="/var/tmp/pip-build"
mkdir -p "$PIP_BUILD_TMPDIR"
export TMPDIR="$PIP_BUILD_TMPDIR"

# Activate the virtual environment
# shellcheck source=/dev/null
source "$VENV_PATH/bin/activate"

_current_step="pip_upgrade"
_inkypi_maybe_inject_failure "pip_upgrade"
# Upgrade pip
echo "Upgrading pip..."
# JTN-665: capture failure so a broken pip/setuptools upgrade does not silently
# proceed to requirements install and leave the venv in a partially-broken state.
# JTN-669: --retries 5 --timeout 60 --no-cache-dir for JTN-534/JTN-602 parity.
if ! "$VENV_PATH/bin/python" -m pip install --retries 5 --timeout 60 --no-cache-dir --upgrade pip setuptools wheel > /dev/null; then
  echo_error "ERROR: pip/setuptools upgrade failed — aborting update."
  exit 1
fi
echo_success "Pip upgraded successfully."

# JTN-669: Try to fetch a pre-built wheelhouse bundle for this version.
# Avoids source-compiling numpy/Pillow/cffi/etc. on every update on
# low-RAM boards like the Pi Zero 2 W (cuts ~15 min / OOM risk down to
# ~2-3 min). Degrades gracefully: any failure falls back to normal pip.
pip_extra_args=()
uv_extra_args=()
if fetch_wheelhouse; then
  pip_extra_args+=(--find-links "$WHEELHOUSE_DIR" --prefer-binary)
  # uv supports --find-links; --find-links pointing at the pre-built wheelhouse
  # already ensures binary wheels are preferred. We omit --only-binary=:all:
  # to avoid blocking packages that only exist as sdists in the wheelhouse.
  uv_extra_args+=(--find-links "$WHEELHOUSE_DIR")
fi

# JTN-670 / JTN-605 parity: Install uv (Rust-based pip replacement) into the
# venv so every update uses the same low-memory installer as fresh installs.
# uv's resolver uses ~10-20 MB peak vs pip's ~100-150 MB — on a 512 MB Pi Zero
# 2 W that difference is the swap cliff.  uv fully honors --require-hashes so
# the JTN-516 supply-chain integrity guarantee is preserved on every update.
#
# We install uv via pip (into the venv) rather than curl-piping from astral.sh:
#   (a) no extra network trust root — uses the same PyPI + hashes we already trust
#   (b) uv is sandboxed inside the venv, not installed to /root/.local
#   (c) if uv itself is unavailable for any reason, we cleanly fall back to pip
use_uv=0
if "$VENV_PATH/bin/python" -m pip install --retries 5 --timeout 60 --no-cache-dir uv > /dev/null 2>&1; then
  if "$VENV_PATH/bin/python" -m uv --version > /dev/null 2>&1; then
    use_uv=1
    echo_success "  uv installed into venv — using uv for dependency install"
  else
    echo "  uv installed but not runnable — falling back to pip for dependency install"
  fi
else
  echo "  uv could not be installed (unsupported arch?) — falling back to pip for dependency install"
fi

# Install or update Python dependencies
# JTN-670: --require-hashes enforces supply-chain integrity on every update
# (JTN-516 parity). Without this, existing Pis that update pull unverified
# wheels even though fresh installs are hash-verified.
_current_step="pip_requirements"
_inkypi_maybe_inject_failure "pip_requirements"
if [ -f "$PIP_REQUIREMENTS_FILE" ]; then
  echo "Updating Python dependencies..."
  # JTN-665: explicit exit-code check so a compile error stops the update
  # before CSS build + service restart, preventing a boot loop.
  # JTN-670/JTN-605: prefer uv; fall back to pip. Both enforce --require-hashes.
  if [[ "$use_uv" -eq 1 ]]; then
    # uv equivalents: --no-cache (not --no-cache-dir), --require-hashes supported.
    # `--python` pins uv to the venv's interpreter so packages land in the venv.
    # UV_HTTP_TIMEOUT scoped to this invocation for flaky Wi-Fi resilience (JTN-534).
    if ! UV_HTTP_TIMEOUT=60 "$VENV_PATH/bin/python" -m uv pip install \
        --python "$VENV_PATH/bin/python" \
        --no-cache \
        "${uv_extra_args[@]}" \
        --require-hashes \
        -r "$PIP_REQUIREMENTS_FILE"; then
      cleanup_wheelhouse
      echo_error "ERROR: uv pip install failed — aborting update (service remains stopped)."
      exit 1
    fi
  else
    # pip fallback: --require-hashes + --no-cache-dir preserve JTN-516/JTN-602 guarantees.
    if ! "$VENV_PATH/bin/python" -m pip install --retries 5 --timeout 60 --no-cache-dir \
        "${pip_extra_args[@]}" \
        --require-hashes \
        -r "$PIP_REQUIREMENTS_FILE"; then
      cleanup_wheelhouse
      echo_error "ERROR: pip install failed — aborting update (service remains stopped)."
      exit 1
    fi
  fi
  cleanup_wheelhouse
  echo_success "Dependencies updated successfully."
else
  cleanup_wheelhouse
  echo_error "ERROR: Requirements file $PIP_REQUIREMENTS_FILE not found!"
  exit 1
fi

# Clean up the pip build temp dir — it can be several hundred MB.
rm -rf "$PIP_BUILD_TMPDIR"
unset TMPDIR

echo "Updating executable in ${BINPATH}/$APPNAME"
cp "$SCRIPT_DIR/inkypi" "$BINPATH/"
sudo chmod +x "$BINPATH/$APPNAME"

_current_step="update_vendors"
_inkypi_maybe_inject_failure "update_vendors"
echo "Update JS and CSS files"
if ! bash "$SCRIPT_DIR/update_vendors.sh" > /dev/null; then
  echo_error "ERROR: Vendor JS/CSS download failed. Check network connectivity and re-run."
  exit 1
fi

# JTN-674: use shared build_css_bundle from _common.sh
# build_css_bundle calls exit 1 internally on failure; under JTN-704 the EXIT
# trap unconditionally clears the lockfile and records the failure step.
_current_step="build_css"
_inkypi_maybe_inject_failure "build_css"
build_css_bundle

_current_step="update_cli"
update_cli

# JTN-685: Remove the lockfile BEFORE starting the service. The ordering bug
# was: update_app_service() called `systemctl start` while the lockfile was
# still present, causing ExecStartPre to reject the start attempt.  All
# dep-install work above is complete; it is now safe to release the lock.
# JTN-704: the EXIT trap also removes this on any exit path, but we remove it
# explicitly here too so update_app_service can start the service even though
# the trap has not fired yet.
rm -f "$LOCKFILE"

_current_step="update_app_service"
_inkypi_maybe_inject_failure "update_app_service"
update_app_service

echo "Version: $(cat "$INSTALL_PATH/VERSION" 2>/dev/null || echo 'unknown')"
echo_success "Update completed."
