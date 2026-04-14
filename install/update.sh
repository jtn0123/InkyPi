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

# JTN-666: Defense-in-depth for JTN-600 parity. While update.sh is running,
# create /var/lib/inkypi/.install-in-progress. inkypi.service's ExecStartPre
# refuses to start if this file exists, so even if someone manually runs
# `systemctl start inkypi.service` or systemd tries to auto-restart, the
# service cannot thrash the Pi mid-update. The lockfile is removed once all
# update steps succeed (see end of script). On failure exit the file is
# deliberately left in place so the user MUST rerun update.sh (or manually
# remove it) before the service can start.
LOCKFILE_DIR="/var/lib/inkypi"
LOCKFILE="$LOCKFILE_DIR/.install-in-progress"

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
    # JTN-684: Explicitly verify the service reached active state.
    # systemctl start exits 0 even when the service subsequently fails
    # (e.g. ExecStart returns non-zero), so we poll is-active with a short
    # retry loop to give systemd a moment to settle before declaring failure.
    local attempts=0
    local max_attempts=3
    local active=0
    while [ "$attempts" -lt "$max_attempts" ]; do
      if sudo systemctl is-active --quiet "$SERVICE_FILE"; then
        active=1
        break
      fi
      attempts=$(( attempts + 1 ))
      [ "$attempts" -lt "$max_attempts" ] && sleep 1
    done
    if [ "$active" -eq 0 ]; then
      echo_error "ERROR: $SERVICE_FILE failed to start (not active after $max_attempts attempt(s))."
      echo "Service status:" >&2
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

# Ensure script is run with sudo
if [ "$EUID" -ne 0 ]; then
  echo_error "ERROR: This script requires root privileges. Please run it with sudo."
  exit 1
fi

# JTN-666: Create the install-in-progress lockfile. inkypi.service's
# ExecStartPre refuses to start while this file exists (defense-in-depth for
# JTN-600's systemctl disable). The lockfile is removed just before
# update_app_service() calls `systemctl start` (see below); on intentional
# failure exit it is left in place so the user must rerun update.sh (or
# manually rm it) before the service can start.
mkdir -p "$LOCKFILE_DIR"
touch "$LOCKFILE"

# JTN-685: Defense-in-depth EXIT trap for abnormal exits (SIGTERM, SIGHUP,
# unhandled errors).  Intentional failure paths (exit 1 after an error message)
# set _lockfile_keep=1 before exiting so the lockfile is intentionally
# preserved — forcing a manual rerun.  Signals and unexpected exits leave
# _lockfile_keep unset, so the trap clears the lockfile and allows the service
# to start after the interruption.
_lockfile_keep=0
trap '[[ "${_lockfile_keep:-0}" -eq 1 ]] || rm -f "$LOCKFILE"' EXIT

# JTN-666: Stop and disable the service BEFORE touching files or venv so
# systemd cannot restart a half-installed service and thrash the Pi.
stop_service

apt-get update -y > /dev/null &
if [ -f "$APT_REQUIREMENTS_FILE" ]; then
  echo "Installing system dependencies... "
  if ! xargs -a "$APT_REQUIREMENTS_FILE" sudo apt-get install -y > /dev/null; then
    echo_error "ERROR: apt-get install failed — aborting update."
    _lockfile_keep=1; exit 1
  fi
  echo_success "Installed system dependencies."
else
  echo_error "ERROR: System dependencies file $APT_REQUIREMENTS_FILE not found!"
  _lockfile_keep=1; exit 1
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

# Check if virtual environment exists
if [ ! -d "$VENV_PATH" ]; then
  echo_error "ERROR: Virtual environment not found at $VENV_PATH. Run the installation script first."
  _lockfile_keep=1; exit 1
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

# Upgrade pip
echo "Upgrading pip..."
# JTN-665: capture failure so a broken pip/setuptools upgrade does not silently
# proceed to requirements install and leave the venv in a partially-broken state.
# JTN-669: --retries 5 --timeout 60 --no-cache-dir for JTN-534/JTN-602 parity.
if ! "$VENV_PATH/bin/python" -m pip install --retries 5 --timeout 60 --no-cache-dir --upgrade pip setuptools wheel > /dev/null; then
  echo_error "ERROR: pip/setuptools upgrade failed — aborting update."
  _lockfile_keep=1; exit 1
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
      _lockfile_keep=1; exit 1
    fi
  else
    # pip fallback: --require-hashes + --no-cache-dir preserve JTN-516/JTN-602 guarantees.
    if ! "$VENV_PATH/bin/python" -m pip install --retries 5 --timeout 60 --no-cache-dir \
        "${pip_extra_args[@]}" \
        --require-hashes \
        -r "$PIP_REQUIREMENTS_FILE"; then
      cleanup_wheelhouse
      echo_error "ERROR: pip install failed — aborting update (service remains stopped)."
      _lockfile_keep=1; exit 1
    fi
  fi
  cleanup_wheelhouse
  echo_success "Dependencies updated successfully."
else
  cleanup_wheelhouse
  echo_error "ERROR: Requirements file $PIP_REQUIREMENTS_FILE not found!"
  _lockfile_keep=1; exit 1
fi

# Clean up the pip build temp dir — it can be several hundred MB.
rm -rf "$PIP_BUILD_TMPDIR"
unset TMPDIR

echo "Updating executable in ${BINPATH}/$APPNAME"
cp "$SCRIPT_DIR/inkypi" "$BINPATH/"
sudo chmod +x "$BINPATH/$APPNAME"

echo "Update JS and CSS files"
if ! bash "$SCRIPT_DIR/update_vendors.sh" > /dev/null; then
  echo_error "ERROR: Vendor JS/CSS download failed. Check network connectivity and re-run."
  _lockfile_keep=1; exit 1
fi

# JTN-674: use shared build_css_bundle from _common.sh
# build_css_bundle calls exit 1 internally on failure — mark as intentional so
# the lockfile is preserved and the user is forced to rerun.
_lockfile_keep=1
build_css_bundle
_lockfile_keep=0

update_cli

# JTN-685: Remove the lockfile BEFORE starting the service. The ordering bug
# was: update_app_service() called `systemctl start` while the lockfile was
# still present, causing ExecStartPre to reject the start attempt.  All
# dep-install work above is complete; it is now safe to release the lock.
rm -f "$LOCKFILE"

update_app_service

echo "Version: $(cat "$INSTALL_PATH/VERSION" 2>/dev/null || echo 'unknown')"
echo_success "Update completed."
