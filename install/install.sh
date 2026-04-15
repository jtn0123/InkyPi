#!/bin/bash

# =============================================================================
# Script Name: install.sh
# Description: This script automates the installation of InkyPI and creation of
#              the InkyPI service.
#
# Usage: ./install.sh [-W <waveshare_device>]
#        -W <waveshare_device> (optional) Install for a Waveshare device,
#                               specifying the device model type, e.g. epd7in3e.
#
#                               If not specified then the Pimoroni Inky display
#                               is assumed.
# =============================================================================

SOURCE=${BASH_SOURCE[0]}
while [ -h "$SOURCE" ]; do # resolve $SOURCE until the file is no longer a symlink
  DIR=$( cd -P "$( dirname "$SOURCE" )" >/dev/null 2>&1 && pwd )
  SOURCE=$(readlink "$SOURCE")
  [[ $SOURCE != /* ]] && SOURCE=$DIR/$SOURCE
done
SCRIPT_DIR=$( cd -P "$( dirname "$SOURCE" )" >/dev/null 2>&1 && pwd )

APPNAME="inkypi"
INSTALL_PATH="/usr/local/$APPNAME"
SRC_PATH="$SCRIPT_DIR/../src"
BINPATH="/usr/local/bin"
VENV_PATH="$INSTALL_PATH/venv_$APPNAME"

# JTN-607: Defense-in-depth for JTN-600. While install.sh is running, create
# /var/lib/inkypi/.install-in-progress. inkypi.service's ExecStartPre refuses
# to start if this file exists, so even if someone manually runs
# `systemctl start inkypi.service` or systemd tries to auto-restart, the
# service cannot thrash the Pi mid-install. The lockfile is removed once all
# install steps succeed (see end of script). On failure exit the file is
# deliberately left in place so the user MUST rerun install.sh (or manually
# remove it) before the service can start.
LOCKFILE_DIR="/var/lib/inkypi"
LOCKFILE="$LOCKFILE_DIR/.install-in-progress"

# JTN-696: Concurrent-install guard. Two `sudo bash install.sh` runs at the
# same time previously raced each other (no lock), producing arbitrary
# file-mix corruption in $INSTALL_PATH. FLOCK_PATH is an advisory fd-based
# lock acquired with `flock -n`; the second caller fails fast.
# /var/lock is the standard FHS location for transient lock files.
FLOCK_PATH="/var/lock/inkypi.install.flock"

SERVICE_FILE="$APPNAME.service"
SERVICE_FILE_SOURCE="$SCRIPT_DIR/$SERVICE_FILE"
SERVICE_FILE_TARGET="/etc/systemd/system/$SERVICE_FILE"

APT_REQUIREMENTS_FILE="$SCRIPT_DIR/debian-requirements.txt"
PIP_REQUIREMENTS_FILE="$SCRIPT_DIR/requirements.txt"

#
# Additional requirements for Waveshare support.
#
# empty means no WS support required, otherwise we expect the type of display
# as per the WS naming convention.
WS_TYPE=""
WS_REQUIREMENTS_FILE="$SCRIPT_DIR/ws-requirements.txt"

# JTN-669/674: Source shared helpers (formatting, stop_service, zramswap,
# earlyoom, get_os_version, build_css_bundle, fetch_wheelhouse, cleanup_wheelhouse)
# so install.sh and update.sh share a single source of truth.
# shellcheck source=install/_common.sh
source "$SCRIPT_DIR/_common.sh"

# Parse the arguments, looking for the -W option.
parse_arguments() {
    while getopts ":W:" opt; do
        case $opt in
            W) WS_TYPE=$OPTARG
                echo "Optional parameter WS is set for Waveshare support.  Screen type is: $WS_TYPE"
                ;;
            \?) echo "Invalid option: -$OPTARG." >&2
                exit 1
                ;;
            :) echo "Option -$OPTARG requires an the model type of the Waveshare screen." >&2
               exit 1
               ;;
        esac
    done
}

check_permissions() {
  # Ensure the script is run with sudo
  if [ "$EUID" -ne 0 ]; then
    echo_error "ERROR: Installation requires root privileges. Please run it with sudo."
    exit 1
  fi
}

fetch_waveshare_driver() {
  echo "Fetching Waveshare driver for: $WS_TYPE"

  DRIVER_DEST="$SRC_PATH/display/waveshare_epd"
  DRIVER_FILE="$DRIVER_DEST/$WS_TYPE.py"
  DRIVER_URL="https://raw.githubusercontent.com/waveshareteam/e-Paper/master/RaspberryPi_JetsonNano/python/lib/waveshare_epd/$WS_TYPE.py"

  # Attempt to download the file
  if [ -f "$DRIVER_FILE" ]; then
    echo_success "\tWaveshare driver '$WS_TYPE.py' already exists at $DRIVER_FILE"
  elif curl --silent --fail -o "$DRIVER_FILE" "$DRIVER_URL"; then
    echo_success "\tWaveshare driver '$WS_TYPE.py' successfully downloaded to $DRIVER_FILE"
  else
    echo_error "ERROR: Failed to download Waveshare driver '$WS_TYPE.py'."
    echo_error "Ensure the model name is correct and exists at:"
    echo_error "https://github.com/waveshareteam/e-Paper/tree/master/RaspberryPi_JetsonNano/python/lib/waveshare_epd"
    exit 1
  fi

  EPD_CONFIG_FILE="$DRIVER_DEST/epdconfig.py"
  EPD_CONFIG_URL="https://raw.githubusercontent.com/waveshareteam/e-Paper/refs/heads/master/RaspberryPi_JetsonNano/python/lib/waveshare_epd/epdconfig.py"
  if [ -f "$EPD_CONFIG_FILE" ]; then
    echo_success "\tWaveshare epdconfig file already exists at $EPD_CONFIG_FILE"
  elif curl --silent --fail -o "$EPD_CONFIG_FILE" "$EPD_CONFIG_URL"; then
    echo_success "\tWaveshare epdconfig file successfully downloaded to $EPD_CONFIG_FILE"
  else
    echo_error "ERROR: Failed to download Waveshare epdconfig file."
    exit 1
  fi
}

enable_interfaces(){
  echo "Enabling interfaces required for $APPNAME"
  local config_txt="/boot/firmware/config.txt"
  if [[ ! -f "$config_txt" ]]; then
    config_txt="/boot/config.txt"
  fi
  if [[ ! -f "$config_txt" ]]; then
    echo_error "ERROR: config.txt not found at /boot/firmware/config.txt or /boot/config.txt"
    exit 1
  fi
  #enable spi
  sudo sed -i 's/^dtparam=spi=.*/dtparam=spi=on/' "$config_txt"
  sudo sed -i 's/^#dtparam=spi=.*/dtparam=spi=on/' "$config_txt"
  sudo raspi-config nonint do_spi 0
  echo_success "\tSPI Interface has been enabled."
  #enable i2c
  sudo sed -i 's/^dtparam=i2c_arm=.*/dtparam=i2c_arm=on/' "$config_txt"
  sudo sed -i 's/^#dtparam=i2c_arm=.*/dtparam=i2c_arm=on/' "$config_txt"
  sudo raspi-config nonint do_i2c 0
  echo_success "\tI2C Interface has been enabled."

  # Is a Waveshare device specified as an install parameter?
  if [[ -n "$WS_TYPE" ]]; then
    # WS parameter is set for Waveshare support so ensure that both CS lines
    # are enabled in the config.txt file.  This is different to INKY which
    # only needs one line set.n
    echo "Enabling both CS lines for SPI interface in config.txt"
    if ! grep -E -q '^[[:space:]]*dtoverlay=spi0-2cs' "$config_txt"; then
        sed -i '/^dtparam=spi=on/a dtoverlay=spi0-2cs' "$config_txt"
    else
        echo "dtoverlay for spi0-2cs already specified"
    fi
  else
    # TODO - check if really need the dtparam set for INKY as this seems to be
    # only for the older screens (as per INKY docs)
    echo "Enabling single CS line for SPI interface in config.txt"
    if ! grep -E -q '^[[:space:]]*dtoverlay=spi0-0cs' "$config_txt"; then
        sed -i '/^dtparam=spi=on/a dtoverlay=spi0-0cs' "$config_txt"
    else
        echo "dtoverlay for spi0-0cs already specified"
    fi
  fi
}

install_debian_dependencies() {
  if [ -f "$APT_REQUIREMENTS_FILE" ]; then
    sudo apt-get update > /dev/null &
    show_loader "Fetch available system dependencies updates. "

    xargs -a "$APT_REQUIREMENTS_FILE" sudo apt-get install -y > /dev/null &
    show_loader "Installing system dependencies. "
  else
    echo "ERROR: System dependencies file $APT_REQUIREMENTS_FILE not found!"
    exit 1
  fi
}

maybe_disable_dphys_swapfile() {
  # JTN-593: When zram is active, dphys-swapfile is dead weight on the SD card
  # (Pi OS Trixie ships both — zram-swap preinstalled + dphys-swapfile preinstalled).
  # Reclaim ~425MB from /var/swap and stop the dphys-swapfile service.
  if ! grep -q "^/dev/zram" /proc/swaps 2>/dev/null; then
    echo "zram swap not active — leaving dphys-swapfile alone."
    return 0
  fi
  if [ ! -f /var/swap ] && ! systemctl list-unit-files dphys-swapfile.service >/dev/null 2>&1; then
    echo "dphys-swapfile not present — nothing to clean up."
    return 0
  fi
  echo "zram swap is active — disabling unused dphys-swapfile and reclaiming /var/swap..."
  if systemctl is-active --quiet dphys-swapfile.service 2>/dev/null; then
    sudo systemctl disable --now dphys-swapfile.service 2>/dev/null || true
  fi
  if command -v dphys-swapfile >/dev/null 2>&1; then
    sudo dphys-swapfile swapoff 2>/dev/null || true
    sudo dphys-swapfile uninstall 2>/dev/null || true
  fi
  if dpkg -l dphys-swapfile 2>/dev/null | grep -q "^ii"; then
    sudo apt-get remove -y dphys-swapfile >/dev/null 2>&1 || true
  fi
  sudo rm -f /var/swap
  echo "✓ Reclaimed dphys-swapfile space."
}

configure_journal_size() {
  local conf="/etc/systemd/journald.conf"
  if [ -f "$conf" ] && ! grep -q "^SystemMaxUse=" "$conf"; then
    echo "Configuring journal size limit (50M)"
    echo "SystemMaxUse=50M" | sudo tee -a "$conf" > /dev/null
    sudo systemctl restart systemd-journald
    echo_success "Journal size limit configured."
  fi
}

create_venv(){
  echo "Creating python virtual environment. "
  python3 -m venv "$VENV_PATH"
  # JTN-534: pass --retries 5 --timeout 60 to survive flaky Wi-Fi on a Pi Zero 2 W.
  # pip's default retries=5 already; explicit so a future change to pip default doesn't bite us.
  # JTN-602: --no-cache-dir saves ~200 MB SD + ~50 MB RAM. Cache has no value
  # on the Pi (pip runs once per install, venv rebuilt on reinstall).
  "$VENV_PATH/bin/python" -m pip install --retries 5 --timeout 60 --no-cache-dir --upgrade pip setuptools wheel > /dev/null

  # JTN-604: Try to fetch a pre-built wheelhouse bundle. When it succeeds,
  # pip/uv can install every dependency from local wheels (no on-device
  # compilation). When it fails, fall through to the normal online install.
  # NOT wrapped in show_loader — fetch prints its own progress and the pip
  # install itself is the step we want visible (see JTN-600).
  local pip_extra_args=()
  local uv_extra_args=()
  if fetch_wheelhouse; then
    pip_extra_args+=(--find-links "$WHEELHOUSE_DIR" --prefer-binary)
    # uv supports --find-links; --only-binary=:all: forces binary wheels to
    # guarantee nothing is built from sdist on the Pi (equivalent intent to
    # pip's --prefer-binary but stricter — uv resolves from a static mapping).
    uv_extra_args+=(--find-links "$WHEELHOUSE_DIR")
  fi

  # JTN-605: Install uv (Rust-based pip replacement from the ruff team) into the
  # venv. uv's resolver uses ~10-20 MB peak vs pip's ~100-150 MB, and installs
  # 3-5x faster on a Pi Zero 2 W. Combined with JTN-604's pre-built wheelhouse,
  # this cuts the dependency-install bottleneck from ~15 min down to ~2-3 min
  # and halves peak memory pressure. `uv pip install` fully honors
  # `--require-hashes` so the JTN-516 supply-chain integrity guarantee is preserved.
  #
  # We install uv via pip (into the venv) rather than curl-piping from astral.sh
  # so:
  #   (a) no extra network trust root — uses the same PyPI + hashes we already trust
  #   (b) uv is sandboxed inside the venv, not installed to /root/.local
  #   (c) if uv itself is unavailable for any reason, we cleanly fall back to pip
  local use_uv=0
  if "$VENV_PATH/bin/python" -m pip install --retries 5 --timeout 60 --no-cache-dir uv > /dev/null 2>&1; then
    if "$VENV_PATH/bin/python" -m uv --version > /dev/null 2>&1; then
      use_uv=1
      echo_success "\tuv installed into venv — using uv for dependency install"
    else
      echo -e "\tuv installed but not runnable — falling back to pip for dependency install"
    fi
  else
    echo -e "\tuv could not be installed (unsupported arch?) — falling back to pip for dependency install"
  fi

  # --require-hashes enforces supply-chain integrity: every wheel is verified
  # against a cryptographic hash before installation.  The lockfile (generated
  # by pip-compile --generate-hashes) contains the expected hashes.
  #
  # JTN-534 parity: the pip fallback sets `--retries 5 --timeout 60` to survive
  # flaky Wi-Fi on a Pi Zero 2 W. uv doesn't accept --default-timeout as a CLI
  # flag; instead it reads UV_HTTP_TIMEOUT (seconds) from the environment. We
  # export it on the same line as the uv invocation so it scopes only to that
  # command and doesn't leak into later subshells. 60s matches the pip fallback.
  if [[ "$use_uv" -eq 1 ]]; then
    # uv equivalents: --no-cache (instead of --no-cache-dir), --require-hashes supported.
    # `--python` pins uv to the venv's interpreter so packages land in the venv.
    UV_HTTP_TIMEOUT=60 "$VENV_PATH/bin/python" -m uv pip install \
      --python "$VENV_PATH/bin/python" \
      --no-cache \
      "${uv_extra_args[@]}" \
      --require-hashes \
      -r "$PIP_REQUIREMENTS_FILE" > /dev/null &
    show_loader "\tInstalling python dependencies (uv). "
  else
    "$VENV_PATH/bin/python" -m pip install --retries 5 --timeout 60 --no-cache-dir \
      "${pip_extra_args[@]}" \
      --require-hashes -r "$PIP_REQUIREMENTS_FILE" -qq > /dev/null &
    show_loader "\tInstalling python dependencies (pip fallback). "
  fi

  # do additional dependencies for Waveshare support.
  if [[ -n "$WS_TYPE" ]]; then
    echo "Adding additional dependencies for waveshare to the python virtual environment. "
    if [[ "$use_uv" -eq 1 ]]; then
      UV_HTTP_TIMEOUT=60 "$VENV_PATH/bin/python" -m uv pip install \
        --python "$VENV_PATH/bin/python" \
        --no-cache \
        "${uv_extra_args[@]}" \
        -r "$WS_REQUIREMENTS_FILE" > ws_pip_install.log &
      show_loader "\tInstalling additional Waveshare python dependencies (uv). "
    else
      "$VENV_PATH/bin/python" -m pip install --retries 5 --timeout 60 --no-cache-dir \
        "${pip_extra_args[@]}" \
        -r "$WS_REQUIREMENTS_FILE" > ws_pip_install.log &
      show_loader "\tInstalling additional Waveshare python dependencies (pip fallback). "
    fi
  fi

  cleanup_wheelhouse
}

install_app_service() {
  echo "Installing $APPNAME systemd service."
  if [ -f "$SERVICE_FILE_SOURCE" ]; then
    cp "$SERVICE_FILE_SOURCE" "$SERVICE_FILE_TARGET"
  else
    echo_error "ERROR: Service file $SERVICE_FILE_SOURCE not found!"
    exit 1
  fi

  # JTN-671/686: Install the failure-sentinel helper unit via shared helper in
  # _common.sh so install.sh and update.sh always copy inkypi-failure.service
  # together with inkypi.service — keeps OnFailure= from dangling after updates.
  install_failure_service_unit

  sudo systemctl daemon-reload
  sudo systemctl enable $SERVICE_FILE
}

install_executable() {
  echo "Adding executable to ${BINPATH}/$APPNAME"
  cp "$SCRIPT_DIR/inkypi" "$BINPATH/"
  sudo chmod +x "$BINPATH/$APPNAME"
}

install_config() {
  CONFIG_BASE_DIR="$SCRIPT_DIR/config_base"
  CONFIG_DIR="$SRC_PATH/config"
  echo "Copying config files to $CONFIG_DIR"

  # Check and copy device.config if it doesn't exist
  if [ ! -f "$CONFIG_DIR/device.json" ]; then
    cp "$CONFIG_BASE_DIR/device.json" "$CONFIG_DIR/"
    show_loader "\tCopying device.config to $CONFIG_DIR"
  else
    echo_success "\tdevice.json already exists in $CONFIG_DIR"
  fi
}

#
# Update the device.json file with the supplied Waveshare parameter (if set).
#
update_config() {
  if [[ -n "$WS_TYPE" ]]; then
      local DEVICE_JSON="$CONFIG_DIR/device.json"

      if grep -q '"display_type":' "$DEVICE_JSON"; then
          # Update existing display_type value
          sed -i "s/\"display_type\": \".*\"/\"display_type\": \"$WS_TYPE\"/" "$DEVICE_JSON"
          echo "Updated display_type to: $WS_TYPE"
      else
          # Append display_type safely, ensuring proper comma placement
          if grep -q '}$' "$DEVICE_JSON"; then
              sed -i '$s/}/,/' "$DEVICE_JSON"  # Replace last } with a comma
          fi
          echo "  \"display_type\": \"$WS_TYPE\"" >> "$DEVICE_JSON"
          echo "}" >> "$DEVICE_JSON"  # Add trailing }
          echo "Added display_type: $WS_TYPE"
      fi
  else
      echo "Config not updated as WS_TYPE flag is not set"
  fi
}

start_service() {
  echo "Starting $APPNAME service."
  sudo systemctl start $SERVICE_FILE
}

install_src() {
  # JTN-696: Build the new install tree in a sibling temp dir, then perform an
  # atomic swap. Previously we removed the target in place before repopulating
  # — Ctrl+C mid-delete left dangling symlinks / a half-populated directory,
  # which crashed the display on next refresh. With the swap pattern,
  # $INSTALL_PATH stays fully populated with the OLD tree until the moment of
  # the rename(2)-family mv -T, so an interruption before the swap leaves the
  # prior install intact.
  echo "Installing $APPNAME to $INSTALL_PATH"

  local parent_dir
  parent_dir=$(dirname "$INSTALL_PATH")
  mkdir -p "$parent_dir"

  # Fresh staging dir. Clean up any leftover from a prior interrupted run.
  INSTALL_STAGING="$INSTALL_PATH.new"
  INSTALL_BACKUP="$INSTALL_PATH.old"
  rm -rf "$INSTALL_STAGING" "$INSTALL_BACKUP"

  mkdir -p "$INSTALL_STAGING"
  ln -sf "$SRC_PATH" "$INSTALL_STAGING/src"
  echo_success "\tStaged new installation at $INSTALL_STAGING"

  # Atomic-ish swap: move old aside, move new into place, then remove old.
  # mv -T treats the destination as a file/dir to overwrite rather than
  # moving INTO it, which is what we want for a directory swap.
  # Service is already stopped+disabled (see stop_service call near the top
  # of install.sh main body) so no process is holding files in $INSTALL_PATH.
  if [[ -d "$INSTALL_PATH" ]]; then
    if ! mv -T "$INSTALL_PATH" "$INSTALL_BACKUP"; then
      echo_error "ERROR: failed to move existing $INSTALL_PATH aside; aborting."
      rm -rf "$INSTALL_STAGING"
      exit 1
    fi
  fi
  if ! mv -T "$INSTALL_STAGING" "$INSTALL_PATH"; then
    echo_error "ERROR: failed to swap staging dir into $INSTALL_PATH; rolling back."
    # Best-effort rollback: restore the prior tree if we moved one aside.
    if [[ -d "$INSTALL_BACKUP" ]]; then
      mv -T "$INSTALL_BACKUP" "$INSTALL_PATH" || true
    fi
    rm -rf "$INSTALL_STAGING"
    exit 1
  fi

  # Swap succeeded. Drop the old tree. If this fails we leave the orphan
  # behind rather than risk touching the fresh install.
  rm -rf "$INSTALL_BACKUP"
  show_loader "\tInstalled $APPNAME to $INSTALL_PATH (atomic swap)"
}

install_cli() {
  rm -rf "$INSTALL_PATH/cli"
  mkdir -p "$INSTALL_PATH/cli"
  cp -a "$SCRIPT_DIR/cli/." "$INSTALL_PATH/cli/"
  sudo chmod +x "$INSTALL_PATH/cli/"*
}

# Get Raspberry Pi hostname
get_hostname() {
  hostname
}

# Get Raspberry Pi IP address
get_ip_address() {
  local ip_address
  ip_address=$(hostname -I | awk '{print $1}')
  echo "$ip_address"
}

ask_for_reboot() {
  # Get hostname and IP address
  local hostname
  local ip_address
  hostname=$(get_hostname)
  ip_address=$(get_ip_address)
  echo_header "$(echo_success "${APPNAME^^} Installation Complete!")"
  echo_header "[•] A reboot of your Raspberry Pi is required for the changes to take effect"
  echo_header "[•] After your Pi is rebooted, you can access the web UI by going to $(echo_blue "'$hostname.local'") or $(echo_blue "'$ip_address'") in your browser."
  echo_header "[•] If you encounter any issues or have suggestions, please submit them here: https://github.com/fatihak/InkyPi/issues"

  read -r -p "Would you like to restart your Raspberry Pi now? [Y/N] " userInput
  userInput="${userInput^^}"

  if [[ "${userInput,,}" == "y" ]]; then
    echo_success "You entered 'Y', rebooting now..."
    sleep 2
    sudo reboot now
  elif [[ "${userInput,,}" == "n" ]]; then
    echo "Please restart your Raspberry Pi later to apply changes by running 'sudo reboot now'."
    exit
  else
    echo "Unknown input, please restart your Raspberry Pi later to apply changes by running 'sudo reboot now'."
    sleep 1
  fi
}

# Wait for NTP sync before proceeding with network-dependent installs.
# Pi Zero 2 W has no RTC battery; on boot, the clock starts at the last
# fake-hwclock value (potentially months out of date). Running pip/apt before
# NTP syncs can cause TLS cert validation failures. See JTN-592.
wait_for_clock() {
  if ! command -v timedatectl >/dev/null 2>&1; then
    echo "timedatectl not available — skipping NTP sync wait."
    return 0
  fi
  echo "Waiting for system clock to sync via NTP (max 60s)..."
  for i in $(seq 1 60); do
    if timedatectl show -p NTPSynchronized --value 2>/dev/null | grep -q yes; then
      echo "✓ Clock synced (took ${i}s)."
      return 0
    fi
    sleep 1
  done
  echo "WARNING: Clock did not sync within 60s. TLS errors during pip install may occur."
  echo "         Current time: $(date -u). If this is wrong, set it manually with:"
  echo "         sudo date -u -s 'YYYY-MM-DD HH:MM:SS'"
  return 0  # don't block install on timeout — warn only
}

# check if we have an argument for WS display support.  Parameter is not required
# to maintain default INKY display support.
parse_arguments "$@"
check_permissions

# JTN-696: Concurrent-install guard. Two simultaneous `sudo bash install.sh`
# runs previously raced through the rm/repopulate sequence in install_src()
# and produced arbitrary corruption. Here we acquire an fd-based advisory
# lock on $FLOCK_PATH; a second caller finds the lock held and exits fast.
# The lock releases automatically when this shell exits (no trap needed).
# -n = non-blocking; -E 42 = exit 42 when the lock cannot be acquired.
if command -v flock >/dev/null 2>&1; then
  mkdir -p "$(dirname "$FLOCK_PATH")"
  exec 9>"$FLOCK_PATH"
  if ! flock -n -E 42 9; then
    rc=$?
    if [ "$rc" -eq 42 ]; then
      echo "ERROR: Another install/update is already running — see $LOCKFILE" >&2
      echo "       (concurrent-install lock $FLOCK_PATH is held)" >&2
    fi
    exit 1
  fi
fi
# flock binary unavailable (non-standard env) — proceed without the guard.

# JTN-607: Create the install-in-progress lockfile. inkypi.service's
# ExecStartPre refuses to start while this file exists (defense-in-depth for
# JTN-600's systemctl disable). The lockfile is removed once all install
# steps succeed (see near end of script); on failure exit it is left in place
# so the user must rerun install.sh (or manually rm it) before the service
# can start.
mkdir -p "$LOCKFILE_DIR"
touch "$LOCKFILE"

# JTN-696: EXIT trap to clean up staging dirs left behind by an interrupted
# install (SIGINT, SIGTERM, or any early exit). Does NOT touch $LOCKFILE —
# JTN-607 deliberately leaves that in place on failure so the user is forced
# to rerun install.sh. Also does NOT touch $INSTALL_PATH itself, so the prior
# install remains intact if the swap never happened.
_cleanup_staging() {
  [[ -n "${INSTALL_PATH:-}" ]] || return 0
  rm -rf "$INSTALL_PATH.new" 2>/dev/null || true
  # Only remove .old if the main $INSTALL_PATH is healthy — otherwise a
  # partially-failed swap may need .old for manual recovery.
  if [[ -d "$INSTALL_PATH" && -L "$INSTALL_PATH/src" ]]; then
    rm -rf "$INSTALL_PATH.old" 2>/dev/null || true
  fi
}
trap _cleanup_staging EXIT

stop_service
# fetch the WS display driver if defined.
if [[ -n "$WS_TYPE" ]]; then
  fetch_waveshare_driver
fi
enable_interfaces
wait_for_clock                # JTN-592: defer until NTP sync to avoid TLS failures
install_debian_dependencies
# Setup zramswap on any modern Pi OS that ships zram-tools (Bullseye/Bookworm/Trixie).
# This is critical on low-RAM boards like the Pi Zero 2 W (512 MB) — without
# zramswap, pip install of numpy/Pillow/playwright will OOM during the install step.
os_version=$(get_os_version)
if [[ "$os_version" =~ ^(11|12|13)$ ]] ; then
  echo "OS version is $os_version (Bullseye/Bookworm/Trixie) - setting up zramswap"
  setup_zramswap_service
else
  echo "OS version is $os_version - skipping zramswap setup (zram-tools not available on this release)."
fi
maybe_disable_dphys_swapfile      # JTN-593: reclaim /var/swap when zram is active
setup_earlyoom_service
configure_journal_size
install_src
install_cli
create_venv
install_executable
install_config
# update the config file with additional WS if defined.
if [[ -n "$WS_TYPE" ]]; then
  update_config
fi

# JTN-695: Vendor download + CSS build must run BEFORE install_app_service so
# that a failure in either step leaves the service untouched. Previously the
# service was enabled first, and a subsequent vendor-download or CSS-build
# failure left the unit enabled while `src/static/styles/main.css` was absent —
# the user would boot into an unstyled web UI with no hint why.
echo "Update JS and CSS files"
# JTN-534: previously the exit code from update_vendors.sh was discarded — a
# transient curl write error during vendor download silently produced a
# half-installed CSS/JS bundle. Fail loudly instead so the user knows.
if ! bash "$SCRIPT_DIR/update_vendors.sh"; then
  echo_error "ERROR: Vendor JS/CSS download failed. Check network connectivity and re-run."
  exit 1
fi

# JTN-674: use shared build_css_bundle from _common.sh
build_css_bundle

# JTN-695: Explicit post-build assertion — main.css must exist AND be non-empty
# before we enable the systemd unit. build_css_bundle already checks existence,
# but a zero-byte file would still pass -f; guard against that too so a silent
# truncation can't leave the service enabled against a blank stylesheet.
MAIN_CSS="$SRC_PATH/static/styles/main.css"
if [ ! -f "$MAIN_CSS" ] || [ ! -s "$MAIN_CSS" ]; then
  echo_error "ERROR: CSS bundle assertion failed — $MAIN_CSS is missing or empty."
  echo_error "Refusing to enable $APPNAME.service with an unusable stylesheet."
  exit 1
fi

# JTN-695: Only now — after vendor download + CSS build + assertion all passed —
# do we enable the systemd unit. A failure in any step above exits before
# touching the service, so `systemctl is-enabled inkypi` reflects reality.
install_app_service

# JTN-607: All install steps succeeded — remove the install-in-progress
# lockfile so the service is allowed to start. If install.sh exits early due
# to a failure above, this line is never reached and the lockfile stays in
# place, forcing the user to rerun install.sh (or manually rm the file)
# before the service can start.
rm -f "$LOCKFILE"

ask_for_reboot
