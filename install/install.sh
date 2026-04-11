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

# Formatting stuff
bold=$(tput bold)
normal=$(tput sgr0)
red=$(tput setaf 1)

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

echo_success() {
  echo -e "$1 [\e[32m\xE2\x9C\x94\e[0m]"
}

echo_override() {
  echo -e "\r$1"
}

echo_header() {
  echo -e "${bold}$1${normal}"
}

echo_error() {
  echo -e "${red}$1${normal} [\e[31m\xE2\x9C\x98\e[0m]\n"
}

echo_blue() {
  echo -e "\e[38;2;65;105;225m$1\e[0m"
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

# JTN-604: Fetch a pre-built wheelhouse bundle from the GitHub release for
# the current VERSION so pip can install every dependency without compiling
# wheels on-device. First-boot install on a Pi Zero 2 W drops from ~15 min
# to ~2-3 min and peak memory pressure drops by ~200 MB (no native builds).
#
# The function is deliberately noisy-but-graceful: on ANY failure (missing
# tarball, 404, checksum mismatch, network glitch, non-matching arch) it
# cleans up and returns non-zero so the caller falls back to normal pip
# install. Users can opt out entirely via INKYPI_SKIP_WHEELHOUSE=1.
#
# Sets WHEELHOUSE_DIR on success; caller passes it to pip via --find-links.
WHEELHOUSE_DIR=""
WHEELHOUSE_REPO="${INKYPI_WHEELHOUSE_REPO:-jtn0123/InkyPi}"

fetch_wheelhouse() {
  WHEELHOUSE_DIR=""

  if [ "${INKYPI_SKIP_WHEELHOUSE:-0}" = "1" ]; then
    echo "  INKYPI_SKIP_WHEELHOUSE=1 set — skipping pre-built wheelhouse."
    return 1
  fi

  if ! command -v curl >/dev/null 2>&1; then
    echo "  curl not available — skipping wheelhouse fetch."
    return 1
  fi

  local version_file="$SCRIPT_DIR/../VERSION"
  if [ ! -f "$version_file" ]; then
    echo "  VERSION file missing — skipping wheelhouse fetch."
    return 1
  fi
  local version
  version=$(tr -d '[:space:]' < "$version_file")
  if [ -z "$version" ]; then
    echo "  VERSION file empty — skipping wheelhouse fetch."
    return 1
  fi

  # Map `uname -m` to the arch tag the workflow publishes.
  local machine arch
  machine=$(uname -m 2>/dev/null || echo "unknown")
  case "$machine" in
    armv7l|armv7|armhf) arch="linux_armv7l" ;;
    aarch64|arm64) arch="linux_aarch64" ;;
    *)
      echo "  Unsupported architecture '$machine' — no pre-built wheels available."
      return 1
      ;;
  esac

  local tarball="inkypi-wheels-${version}-${arch}.tar.gz"
  local url="https://github.com/${WHEELHOUSE_REPO}/releases/download/v${version}/${tarball}"
  local sha_url="${url}.sha256"
  local tmp_dir tmp_tarball tmp_sha
  tmp_dir=$(mktemp -d -t inkypi-wheels.XXXXXX) || return 1
  tmp_tarball="${tmp_dir}/${tarball}"
  tmp_sha="${tmp_dir}/${tarball}.sha256"

  echo "  Fetching pre-built wheelhouse for ${arch} (v${version})..."
  if ! curl --fail --silent --show-error --location \
        --retry 3 --retry-delay 2 --connect-timeout 10 --max-time 300 \
        --output "$tmp_tarball" "$url" 2>/dev/null; then
    echo "  Wheelhouse not available at $url — falling back to source install."
    rm -rf "$tmp_dir"
    return 1
  fi

  # SHA256 is optional but preferred. Verify when present.
  if curl --fail --silent --show-error --location \
        --retry 2 --connect-timeout 10 --max-time 30 \
        --output "$tmp_sha" "$sha_url" 2>/dev/null; then
    # sha256sum prints "<hash>  <filename>"; compare against the downloaded file.
    local expected actual
    expected=$(awk '{print $1}' "$tmp_sha" 2>/dev/null || echo "")
    if command -v sha256sum >/dev/null 2>&1; then
      actual=$(sha256sum "$tmp_tarball" | awk '{print $1}')
    elif command -v shasum >/dev/null 2>&1; then
      actual=$(shasum -a 256 "$tmp_tarball" | awk '{print $1}')
    else
      actual=""
    fi
    if [ -n "$expected" ] && [ -n "$actual" ] && [ "$expected" != "$actual" ]; then
      echo "  Wheelhouse checksum mismatch — falling back to source install."
      rm -rf "$tmp_dir"
      return 1
    fi
  fi

  local extract_dir="${tmp_dir}/wheels"
  mkdir -p "$extract_dir"
  if ! tar -xzf "$tmp_tarball" -C "$extract_dir" 2>/dev/null; then
    echo "  Failed to extract wheelhouse tarball — falling back to source install."
    rm -rf "$tmp_dir"
    return 1
  fi

  # Sanity check: at least one .whl must exist, otherwise the bundle is empty.
  if ! find "$extract_dir" -name '*.whl' -print -quit | grep -q .; then
    echo "  Wheelhouse tarball contained no wheel files — falling back."
    rm -rf "$tmp_dir"
    return 1
  fi

  WHEELHOUSE_DIR="$extract_dir"
  echo_success "  Pre-built wheelhouse ready at $WHEELHOUSE_DIR"
  return 0
}

cleanup_wheelhouse() {
  if [ -n "$WHEELHOUSE_DIR" ] && [ -d "$WHEELHOUSE_DIR" ]; then
    # Remove the parent mktemp dir (contains wheelhouse + tarball + sha).
    rm -rf "$(dirname "$WHEELHOUSE_DIR")"
    WHEELHOUSE_DIR=""
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
  # pip can install every dependency from local wheels (no on-device
  # compilation). When it fails, fall through to the normal online install.
  # NOT wrapped in show_loader — fetch prints its own progress and the pip
  # install itself is the step we want visible (see JTN-600).
  local pip_extra_args=()
  if fetch_wheelhouse; then
    pip_extra_args+=(--find-links "$WHEELHOUSE_DIR" --prefer-binary)
  fi

  # --require-hashes enforces supply-chain integrity: every wheel is verified
  # against a cryptographic hash before installation.  The lockfile (generated
  # by pip-compile --generate-hashes) contains the expected hashes.
  "$VENV_PATH/bin/python" -m pip install --retries 5 --timeout 60 --no-cache-dir \
    "${pip_extra_args[@]}" \
    --require-hashes -r "$PIP_REQUIREMENTS_FILE" -qq > /dev/null &
  show_loader "\tInstalling python dependencies. "

  # do additional dependencies for Waveshare support.
  if [[ -n "$WS_TYPE" ]]; then
    echo "Adding additional dependencies for waveshare to the python virtual environment. "
    "$VENV_PATH/bin/python" -m pip install --retries 5 --timeout 60 --no-cache-dir \
      "${pip_extra_args[@]}" \
      -r "$WS_REQUIREMENTS_FILE" > ws_pip_install.log &
    show_loader "\tInstalling additional Waveshare python dependencies. "
  fi

  cleanup_wheelhouse
}

install_app_service() {
  echo "Installing $APPNAME systemd service."
  if [ -f "$SERVICE_FILE_SOURCE" ]; then
    cp "$SERVICE_FILE_SOURCE" "$SERVICE_FILE_TARGET"
    sudo systemctl daemon-reload
    sudo systemctl enable $SERVICE_FILE
  else
    echo_error "ERROR: Service file $SERVICE_FILE_SOURCE not found!"
    exit 1
  fi
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

stop_service() {
    echo "Checking if $SERVICE_FILE is running"
    if /usr/bin/systemctl is-active --quiet "$SERVICE_FILE"
    then
      /usr/bin/systemctl stop "$SERVICE_FILE" > /dev/null &
      show_loader "Stopping $APPNAME service"
    else
      echo_success "\t$SERVICE_FILE not running"
    fi
    # JTN-600: DISABLE (not just stop) during install so systemd cannot
    # restart the half-installed service and thrash the Pi. install_app_service
    # re-enables it at the end of the install.
    /usr/bin/systemctl disable "$SERVICE_FILE" 2>/dev/null || true
}

start_service() {
  echo "Starting $APPNAME service."
  sudo systemctl start $SERVICE_FILE
}

install_src() {
  # Check if an existing installation is present
  echo "Installing $APPNAME to $INSTALL_PATH"
  if [[ -d "$INSTALL_PATH" ]]; then
    rm -rf "$INSTALL_PATH" > /dev/null
    show_loader "\tRemoving existing installation found at $INSTALL_PATH"
  fi

  mkdir -p "$INSTALL_PATH"

  ln -sf "$SRC_PATH" "$INSTALL_PATH/src"
  show_loader "\tCreating symlink from $SRC_PATH to $INSTALL_PATH/src"
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

# Get OS release number, e.g. 11=Bullseye, 12=Bookworm, 13=Trixie
get_os_version() {
  lsb_release -sr
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
install_app_service

echo "Update JS and CSS files"
# JTN-534: previously the exit code from update_vendors.sh was discarded — a
# transient curl write error during vendor download silently produced a
# half-installed CSS/JS bundle. Fail loudly instead so the user knows.
if ! bash "$SCRIPT_DIR/update_vendors.sh"; then
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

ask_for_reboot
