#!/bin/bash
# boot-health.sh — decide whether a failing InkyPi install should roll itself
# back, and do it.
#
# The gap this closes: rollback.sh has always worked, but only when a human ran
# it or clicked it in the settings UI. A device that updates itself into a
# non-starting state cannot serve the UI that offers the button, so recovery
# needed physical access — which is exactly what a headless frame on a shelf
# does not have.
#
# The scheme is lifted from the ESP32-Garage-Fan firmware
# (firmware/arduino/src/system/boot_health.h), which solved the same problem for
# an OTA image that boots but never reaches the network:
#
#   * a counter tracks consecutive start-limit events (see
#     BOOT_HEALTH_MAX_UNHEALTHY — systemd reports these, not individual
#     failed starts);
#   * a separate record remembers the last version that was ever CONFIRMED
#     healthy (serving, and reporting the version we installed);
#   * at decision time we roll back only when the running version has never
#     been confirmed AND the failure streak has hit the threshold.
#
# That last condition is the important one. A version that worked before and is
# failing now points at the environment — a full disk, a yanked SD card, a
# broken dependency in the OS — and swapping versions would regress the install
# without fixing anything. Only a never-confirmed version is evidence that the
# update itself is at fault.
#
# Invoked by inkypi-failure.service (OnFailure= in inkypi.service), which fires
# once systemd gives up retrying under StartLimitBurst.

set -uo pipefail

SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do
  DIR=$( cd -P "$( dirname "$SOURCE" )" >/dev/null 2>&1 && pwd )
  SOURCE=$(readlink "$SOURCE")
  [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"
done
SCRIPT_DIR=$( cd -P "$( dirname "$SOURCE" )" >/dev/null 2>&1 && pwd )

STATE_DIR="${INKYPI_LOCKFILE_DIR:-/var/lib/inkypi}"
FAILED_STARTS_FILE="$STATE_DIR/failed_starts"
CONFIRMED_VERSION_FILE="$STATE_DIR/confirmed_version"
PREV_VERSION_FILE="$STATE_DIR/prev_version"
ROLLBACK_MARKER="$STATE_DIR/.auto-rollback-attempted"

# Consecutive START-LIMIT EVENTS of a never-confirmed version before we roll
# back.
#
# The unit counts differently from the firmware this scheme came from. systemd
# calls OnFailure= once, when inkypi.service exhausts StartLimitBurst (5) and
# enters the failed state — not once per failed start. So one increment here
# already represents five failed attempts, and systemd then stops retrying
# until the unit is reset or the device reboots. A threshold of 3 would have
# required three separate start-limit episodes (≈15 failed starts across
# multiple boots) before rolling back, which is far later than "three unhealthy
# boots" implies.
#
# 2 keeps one episode's worth of benefit-of-the-doubt for a transient (a bad SD
# read, a slow mount) while still recovering on the next boot.
BOOT_HEALTH_MAX_UNHEALTHY="${INKYPI_BOOT_HEALTH_MAX_UNHEALTHY:-2}"
if ! [[ "$BOOT_HEALTH_MAX_UNHEALTHY" =~ ^[1-9][0-9]*$ ]]; then
  BOOT_HEALTH_MAX_UNHEALTHY=3
fi

# ---------------------------------------------------------------------------
# Pure decision logic.
#
# Kept free of filesystem and systemd access, exactly as the firmware keeps
# boot_health.h free of Arduino headers, so the rule can be tested directly
# instead of through a simulated failing install.
#
#   $1 — consecutive start-limit events, INCLUDING the one being decided
#   $2 — "yes" when the running version has previously been confirmed healthy
#
# Returns 0 (true) when the caller should roll back.
# ---------------------------------------------------------------------------
boot_health_should_rollback() {
  local failed_starts="$1" running_confirmed="$2"
  if [ "$running_confirmed" = "yes" ]; then
    return 1
  fi
  if ! [[ "$failed_starts" =~ ^[0-9]+$ ]]; then
    return 1
  fi
  [ "$failed_starts" -ge "$BOOT_HEALTH_MAX_UNHEALTHY" ]
}

_read_file() {
  local path="$1"
  [ -r "$path" ] && tr -d '[:space:]' < "$path" 2>/dev/null || printf ''
}

#: Stand-in used when VERSION cannot be read, so "confirmed" and "running"
#: still compare equal instead of both being empty and never matching.
UNKNOWN_VERSION="unknown"

_current_version() {
  local version
  version=$(_read_file "$SCRIPT_DIR/../VERSION")
  printf '%s' "${version:-$UNKNOWN_VERSION}"
}

# Record the running version as healthy and clear the failure streak. Called by
# update.sh once verification confirms the new build is genuinely serving.
boot_health_mark_confirmed() {
  local version="${1:-$(_current_version)}"
  mkdir -p "$STATE_DIR" 2>/dev/null || true
  # Record something even when VERSION is unreadable. Skipping the write left
  # the install permanently unconfirmed, so a build that had been verified
  # healthy stayed eligible for rollback for the rest of its life. The sentinel
  # matches what _current_version reports in the same situation, so the
  # "has this version ever worked?" comparison still lines up.
  printf '%s\n' "${version:-$UNKNOWN_VERSION}" > "$CONFIRMED_VERSION_FILE" 2>/dev/null || true
  rm -f "$FAILED_STARTS_FILE" "$ROLLBACK_MARKER" 2>/dev/null || true
}

# Count this failure and roll back if the rule says so.
boot_health_record_failure() {
  mkdir -p "$STATE_DIR" 2>/dev/null || true

  local failed_starts
  failed_starts=$(_read_file "$FAILED_STARTS_FILE")
  [[ "$failed_starts" =~ ^[0-9]+$ ]] || failed_starts=0
  failed_starts=$((failed_starts + 1))
  printf '%s\n' "$failed_starts" > "$FAILED_STARTS_FILE" 2>/dev/null || true

  local current confirmed running_confirmed="no"
  current=$(_current_version)
  confirmed=$(_read_file "$CONFIRMED_VERSION_FILE")
  if [ -n "$current" ] && [ "$current" = "$confirmed" ]; then
    running_confirmed="yes"
  fi

  echo "boot-health: start-limit event #$failed_starts for version '${current:-unknown}'" \
    "(last confirmed healthy: '${confirmed:-none}')"

  if ! boot_health_should_rollback "$failed_starts" "$running_confirmed"; then
    if [ "$running_confirmed" = "yes" ]; then
      echo "boot-health: this version has been healthy before — not rolling back." \
        "Investigate the environment rather than the build."
    fi
    return 0
  fi

  # One attempt only. If the rolled-back version also fails to start, rolling
  # back again would flip between two broken versions forever, wearing the SD
  # card and never converging. Stop and leave the evidence for a human.
  if [ -e "$ROLLBACK_MARKER" ]; then
    echo "boot-health: automatic rollback already attempted; not retrying." >&2
    return 0
  fi

  if [ ! -s "$PREV_VERSION_FILE" ]; then
    echo "boot-health: no previous version recorded; cannot roll back." >&2
    return 0
  fi

  local rollback_script="$SCRIPT_DIR/rollback.sh"
  if [ ! -x "$rollback_script" ] && [ ! -f "$rollback_script" ]; then
    echo "boot-health: rollback.sh not found at $rollback_script" >&2
    return 0
  fi

  touch "$ROLLBACK_MARKER" 2>/dev/null || true
  echo "boot-health: rolling back to $(_read_file "$PREV_VERSION_FILE")" \
    "after $failed_starts start-limit events of an unconfirmed version."
  bash "$rollback_script"
}

# Only run the action when executed; sourcing (tests, update.sh) just loads the
# functions above.
if ! (return 0 2>/dev/null); then
  boot_health_record_failure
fi
