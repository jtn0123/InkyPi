#!/usr/bin/env bash

set -euo pipefail

APPNAME="inkypi"
UNIT="$APPNAME.service"
REMOTE_HOST=""
SSH_PORT=""
NUM_LINES=200
FOLLOW=0
SINCE=""
GREP_PATTERN=""
OUTPUT_FORMAT="cat"  # or short-iso for timestamps

print_usage() {
  cat <<USAGE
Usage: $(basename "$0") [options]

Stream or tail systemd logs for $UNIT locally or over SSH.

Options:
  -u <unit>       Override systemd unit (default: $UNIT)
  -n <lines>      Number of lines to show (default: $NUM_LINES)
  -f              Follow logs (stream)
  -S <since>      journalctl --since value (e.g. "10m ago", "yesterday")
  -g <pattern>    Regex filter (server-side if supported by journalctl)
  -T              Show timestamps (uses -o short-iso)
  -r <user@host>  Remote SSH host (e.g. pi@raspberrypi.local)
  -p <port>       SSH port (optional)
  -h              Show this help

Examples:
  # Local: follow live logs
  $(basename "$0") -f

  # Remote: last 300 lines and follow
  $(basename "$0") -r pi@raspberrypi.local -n 300 -f

  # Filter errors from last 15 minutes
  $(basename "$0") -S "15m ago" -g "error|traceback"
USAGE
}

while getopts ":u:n:fS:g:Tr:p:h" opt; do
  case "$opt" in
    u) UNIT="$OPTARG" ;;
    n) NUM_LINES="$OPTARG" ;;
    f) FOLLOW=1 ;;
    S) SINCE="$OPTARG" ;;
    g) GREP_PATTERN="$OPTARG" ;;
    T) OUTPUT_FORMAT="short-iso" ;;
    r) REMOTE_HOST="$OPTARG" ;;
    p) SSH_PORT="$OPTARG" ;;
    h) print_usage; exit 0 ;;
    :) echo "Option -$OPTARG requires an argument" >&2; print_usage; exit 1 ;;
    \?) echo "Invalid option: -$OPTARG" >&2; print_usage; exit 1 ;;
  esac
done

FOLLOW_FLAG=""
if [[ "$FOLLOW" -eq 1 ]]; then
  FOLLOW_FLAG="-f"
fi

SINCE_FLAG=""
if [[ -n "$SINCE" ]]; then
  SINCE_FLAG="--since=$SINCE"
fi

GREP_FLAG=""
if [[ -n "$GREP_PATTERN" ]]; then
  # Prefer server-side grep if supported by journalctl (most modern systems)
  GREP_FLAG="--grep=$GREP_PATTERN"
  # Fallback could pipe to grep, but avoid unless necessary
fi

JOURNAL_CMD=(journalctl -u "$UNIT" -n "$NUM_LINES" --no-pager -o "$OUTPUT_FORMAT")
if [[ -n "$FOLLOW_FLAG" ]]; then
  JOURNAL_CMD+=("$FOLLOW_FLAG")
fi
if [[ -n "$SINCE_FLAG" ]]; then
  JOURNAL_CMD+=("$SINCE_FLAG")
fi
if [[ -n "$GREP_FLAG" ]]; then
  JOURNAL_CMD+=("$GREP_FLAG")
fi

if [[ -n "$REMOTE_HOST" ]]; then
  SSH_ARGS=("$REMOTE_HOST")
  if [[ -n "$SSH_PORT" ]]; then
    SSH_ARGS=("-p" "$SSH_PORT" "$REMOTE_HOST")
  fi
  # shellcheck disable=SC2029
  exec ssh -t "${SSH_ARGS[@]}" "${JOURNAL_CMD[@]}"
else
  exec "${JOURNAL_CMD[@]}"
fi


