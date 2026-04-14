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

echo_success() {
  echo -e "$1 [\e[32m\xE2\x9C\x94\e[0m]"
}

echo_error() {
  echo -e "$1 [\e[31m\xE2\x9C\x98\e[0m]\n"
}

show_loader() {
  local pid=$!
  local message="$1"
  local delay=0.1
  local spinstr="|/-\\"
  printf "%s [%s] " "$message" "${spinstr:0:1}"
  while kill -0 "$pid" 2>/dev/null; do
    local temp=${spinstr#?}
    printf "\r%s [%s] " "$message" "${temp:0:1}"
    spinstr=${temp}${spinstr%"${temp}"}
    sleep "${delay}"
  done
  if wait "$pid"; then
    printf "\r%s [\e[32m\xE2\x9C\x94\e[0m]\n" "$message"
  else
    printf "\r%s [\e[31m\xE2\x9C\x98\e[0m]\n" "$message"
  fi
}

setup_zramswap_service() {
  # If the OS already provides zram swap (e.g. Pi OS Trixie preinstalls zram-swap),
  # skip zram-tools — they fight over /dev/zram0 and cause mkswap to fail.
  if grep -q "^/dev/zram" /proc/swaps 2>/dev/null; then
    echo "zram swap already active (likely from preinstalled zram-swap package) — skipping zram-tools install."
    return 0
  fi
  echo "Enabling and starting zramswap service."
  sudo apt-get install -y zram-tools > /dev/null
  echo -e "ALGO=zstd\nPERCENT=60" | sudo tee /etc/default/zramswap > /dev/null
  sudo systemctl enable --now zramswap
}

setup_earlyoom_service() {
  echo "Enabling and starting earlyoom service."
  sudo apt-get install -y earlyoom > /dev/null
  sudo systemctl enable --now earlyoom
}

# JTN-666: Stop and DISABLE (not just stop) the service before touching the
# venv or app files. This mirrors install.sh:539-552 (JTN-600). systemd cannot
# restart a half-installed service during the update, preventing the load-14
# thrash observed on Pi Zero 2 W.
stop_service() {
  echo "Checking if $SERVICE_FILE is running"
  if /usr/bin/systemctl is-active --quiet "$SERVICE_FILE"; then
    /usr/bin/systemctl stop "$SERVICE_FILE" > /dev/null &
    show_loader "Stopping $APPNAME service"
  else
    echo_success "\t$SERVICE_FILE not running"
  fi
  # DISABLE (not just stop) during update so systemd cannot restart the
  # half-installed service. update_app_service re-enables it at the end.
  /usr/bin/systemctl disable "$SERVICE_FILE" 2>/dev/null || true
}

update_app_service() {
  echo "Updating $APPNAME systemd service."
  if [ -f "$SERVICE_FILE_SOURCE" ]; then
    sudo cp "$SERVICE_FILE_SOURCE" "$SERVICE_FILE_TARGET"
    sudo systemctl daemon-reload
    sudo systemctl enable "$SERVICE_FILE"
    echo "Starting $APPNAME service."
    sudo systemctl start "$SERVICE_FILE"
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

# Get OS release number, e.g. 11=Bullseye, 12=Bookworm, 13=Trixie
get_os_version() {
  lsb_release -sr
}


# Ensure script is run with sudo
if [ "$EUID" -ne 0 ]; then
  echo_error "ERROR: This script requires root privileges. Please run it with sudo."
  exit 1
fi

# JTN-666: Create the install-in-progress lockfile. inkypi.service's
# ExecStartPre refuses to start while this file exists (defense-in-depth for
# JTN-600's systemctl disable). The lockfile is removed once all update steps
# succeed (see near end of script); on failure exit it is left in place so the
# user must rerun update.sh (or manually rm it) before the service can start.
mkdir -p "$LOCKFILE_DIR"
touch "$LOCKFILE"

# JTN-666: Stop and disable the service BEFORE touching files or venv so
# systemd cannot restart a half-installed service and thrash the Pi.
stop_service

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

# Upgrade pip
echo "Upgrading pip..."
# JTN-665: capture failure so a broken pip/setuptools upgrade does not silently
# proceed to requirements install and leave the venv in a partially-broken state.
if ! "$VENV_PATH/bin/python" -m pip install --retries 5 --timeout 60 --no-cache-dir --upgrade pip setuptools wheel > /dev/null; then
  echo_error "ERROR: pip/setuptools upgrade failed — aborting update."
  exit 1
fi
echo_success "Pip upgraded successfully."

# Install or update Python dependencies
if [ -f "$PIP_REQUIREMENTS_FILE" ]; then
  echo "Updating Python dependencies..."
  # JTN-665: explicit exit-code check so a compile error (e.g. metadata-generation-failed)
  # stops the update before CSS build + service restart, preventing a boot loop.
  if ! "$VENV_PATH/bin/python" -m pip install --retries 5 --timeout 60 --no-cache-dir --upgrade -r "$PIP_REQUIREMENTS_FILE" -qq > /dev/null; then
    echo_error "ERROR: pip install failed — aborting update (service remains stopped)."
    exit 1
  fi
  echo_success "Dependencies updated successfully."
else
  echo_error "ERROR: Requirements file $PIP_REQUIREMENTS_FILE not found!"
  exit 1
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
  exit 1
fi

echo "Building minified CSS bundle"
if ! "$VENV_PATH/bin/python" "$SCRIPT_DIR/../scripts/build_css.py" --minify; then
  echo_error "ERROR: CSS build failed. The web UI will not render correctly."
  exit 1
fi
CSS_OUTPUT="$SCRIPT_DIR/../src/static/styles/main.css"
if [ ! -f "$CSS_OUTPUT" ]; then
  echo_error "ERROR: CSS bundle was not generated at $CSS_OUTPUT."
  exit 1
fi
echo_success "CSS bundle built."

update_cli
update_app_service

# JTN-666: All update steps succeeded — remove the install-in-progress lockfile
# so the service is allowed to start. If update.sh exits early due to a failure
# above, this line is never reached and the lockfile stays in place, forcing the
# user to rerun update.sh (or manually rm the file) before the service can start.
rm -f "$LOCKFILE"

echo "Version: $(cat "$INSTALL_PATH/VERSION" 2>/dev/null || echo 'unknown')"
echo_success "Update completed."
