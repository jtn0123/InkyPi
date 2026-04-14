#!/bin/bash

# =============================================================================
# _common.sh — shared helpers sourced by install.sh and update.sh
#
# JTN-669: Extracted from install.sh so update.sh can also use the pre-built
# wheelhouse (JTN-604), avoiding source-compilation of numpy/Pillow/cffi/etc.
# on every update on low-RAM boards like the Pi Zero 2 W.
# =============================================================================

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
#
# Requires SCRIPT_DIR and WHEELHOUSE_REPO to be set by the sourcing script.
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
