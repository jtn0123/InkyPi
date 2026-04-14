#!/bin/bash

# =============================================================================
# _common.sh — shared helpers sourced by install.sh and update.sh
#
# JTN-669: Extracted fetch_wheelhouse/cleanup_wheelhouse so update.sh can use
# pre-built wheels (JTN-604), avoiding source-compilation on every update.
#
# JTN-674: Extended to cover all remaining duplicated logic so install.sh and
# update.sh share a single source of truth:
#   - Formatting helpers (echo_success / echo_error / echo_header / echo_blue /
#     echo_override / show_loader)
#   - get_os_version
#   - setup_zramswap_service / setup_earlyoom_service
#   - stop_service
#   - build_css_bundle
# =============================================================================

# ---------------------------------------------------------------------------
# Terminal formatting (requires tput; safe to call in non-interactive shells)
# ---------------------------------------------------------------------------
bold=$(tput bold 2>/dev/null || true)
normal=$(tput sgr0 2>/dev/null || true)
red=$(tput setaf 1 2>/dev/null || true)

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

# ---------------------------------------------------------------------------
# OS helpers
# ---------------------------------------------------------------------------

# Get OS release number, e.g. 11=Bullseye, 12=Bookworm, 13=Trixie
get_os_version() {
  lsb_release -sr
}

# ---------------------------------------------------------------------------
# Service helpers
# ---------------------------------------------------------------------------

# Stop and DISABLE (not just stop) the service so systemd cannot restart a
# half-installed service during install/update. The caller is responsible for
# re-enabling and starting the service once all steps succeed.
#
# Requires SERVICE_FILE and APPNAME to be set by the sourcing script.
stop_service() {
  echo "Checking if $SERVICE_FILE is running"
  if /usr/bin/systemctl is-active --quiet "$SERVICE_FILE"; then
    /usr/bin/systemctl stop "$SERVICE_FILE" > /dev/null &
    show_loader "Stopping $APPNAME service"
  else
    echo_success "\t$SERVICE_FILE not running"
  fi
  # DISABLE (not just stop) during install/update so systemd cannot restart the
  # half-installed service. The caller re-enables it at the end of the script.
  /usr/bin/systemctl disable "$SERVICE_FILE" 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# Memory-pressure helpers
# ---------------------------------------------------------------------------

setup_zramswap_service() {
  # If the OS already provides zram swap (e.g. Pi OS Trixie preinstalls
  # zram-swap), skip zram-tools — they fight over /dev/zram0 and cause mkswap
  # to fail.
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

# ---------------------------------------------------------------------------
# CSS build helper
#
# Requires VENV_PATH and SCRIPT_DIR to be set by the sourcing script.
# ---------------------------------------------------------------------------

build_css_bundle() {
  echo "Building minified CSS bundle"
  if ! "$VENV_PATH/bin/python" "$SCRIPT_DIR/../scripts/build_css.py" --minify; then
    echo_error "ERROR: CSS build failed. The web UI will not render correctly."
    exit 1
  fi
  local css_output="$SCRIPT_DIR/../src/static/styles/main.css"
  if [ ! -f "$css_output" ]; then
    echo_error "ERROR: CSS bundle was not generated at $css_output."
    exit 1
  fi
  echo_success "CSS bundle built."
}

# ---------------------------------------------------------------------------
# Systemd unit helpers (JTN-686)
#
# install_failure_service_unit — copy inkypi-failure.service to
# /etc/systemd/system/. Called by both install.sh and update.sh so every code
# path that refreshes the main inkypi.service unit also refreshes the
# OnFailure= sentinel unit.  Not enabled (it is activated via OnFailure=).
#
# Requires SCRIPT_DIR to be set by the sourcing script.
# ---------------------------------------------------------------------------

install_failure_service_unit() {
  local src="$SCRIPT_DIR/inkypi-failure.service"
  local dst="/etc/systemd/system/inkypi-failure.service"
  if [ -f "$src" ]; then
    cp "$src" "$dst"
  else
    echo_error "ERROR: Failure service file $src not found!"
    exit 1
  fi
}

# ---------------------------------------------------------------------------
# Wheelhouse helpers (JTN-604 / JTN-669)
#
# fetch_wheelhouse / cleanup_wheelhouse — extracted in PR #450.
# Require SCRIPT_DIR and WHEELHOUSE_REPO to be set (WHEELHOUSE_REPO defaults
# below). Sets WHEELHOUSE_DIR on success so callers can pass --find-links.
# ---------------------------------------------------------------------------

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
  local manifest_url="https://github.com/${WHEELHOUSE_REPO}/releases/download/v${version}/${tarball}.manifest.sha256"
  local tmp_dir tmp_tarball tmp_sha tmp_manifest
  tmp_dir=$(mktemp -d -t inkypi-wheels.XXXXXX) || return 1
  tmp_tarball="${tmp_dir}/${tarball}"
  tmp_sha="${tmp_dir}/${tarball}.sha256"
  tmp_manifest="${tmp_dir}/${tarball}.manifest.sha256"

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

  # JTN-697: Integrity-verify every extracted wheel. A tarball can decompress
  # cleanly and pass the outer sha256 check yet still contain a zero-byte
  # numpy-*.whl (e.g. if the producer truncated mid-write). pip happily
  # "installs" those and the ImportError only surfaces on first refresh.
  #
  # Two layers:
  #   1. If a per-wheel sha256 manifest was published (preferred), verify
  #      every wheel's hash against the manifest. Any mismatch → fall back.
  #   2. Structural fallback for older releases without a manifest: reject
  #      empty files and anything that isn't a readable zip archive.
  local sha256_cmd=""
  if command -v sha256sum >/dev/null 2>&1; then
    sha256_cmd="sha256sum"
  elif command -v shasum >/dev/null 2>&1; then
    sha256_cmd="shasum -a 256"
  fi

  local have_manifest=0
  if curl --fail --silent --show-error --location \
        --retry 2 --connect-timeout 10 --max-time 30 \
        --output "$tmp_manifest" "$manifest_url" 2>/dev/null; then
    if [ -s "$tmp_manifest" ] && [ -n "$sha256_cmd" ]; then
      have_manifest=1
    fi
  fi

  local whl
  while IFS= read -r -d '' whl; do
    # Guard 1: wheel must be non-empty. A truncated tarball can leave a
    # 0-byte placeholder even after tar reports success.
    if [ ! -s "$whl" ]; then
      echo "  Wheelhouse integrity check failed: empty wheel $(basename "$whl") — falling back."
      rm -rf "$tmp_dir"
      return 1
    fi
    # Guard 2: wheel must be a readable zip (pip won't install otherwise).
    # We deliberately use python -m zipfile rather than unzip because the
    # install base always has python available but unzip is not guaranteed.
    if command -v python3 >/dev/null 2>&1; then
      if ! python3 -m zipfile -l "$whl" >/dev/null 2>&1; then
        echo "  Wheelhouse integrity check failed: $(basename "$whl") is not a valid zip — falling back."
        rm -rf "$tmp_dir"
        return 1
      fi
    fi
  done < <(find "$extract_dir" -name '*.whl' -type f -print0)

  # Guard 3 (preferred): verify each wheel against the published manifest.
  # Manifest format is `sha256sum` output: "<hash>  <basename>\n" per wheel.
  if [ "$have_manifest" = "1" ]; then
    # Run sha256sum -c from the extract dir so the basenames in the manifest
    # line up with the extracted files. --quiet suppresses per-line OK output
    # but still emits mismatches, and the exit code is non-zero on any fail.
    if ! ( cd "$extract_dir" && $sha256_cmd -c "$tmp_manifest" --quiet >/dev/null 2>&1 ); then
      echo "  Wheelhouse manifest sha256 mismatch — falling back to source install."
      rm -rf "$tmp_dir"
      return 1
    fi
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
