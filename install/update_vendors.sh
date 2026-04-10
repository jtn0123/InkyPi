#!/usr/bin/env bash

set -euo pipefail

# Versions
SELECT2_VERSION="4.1.0-beta.1"
FULLCALENDAR_VERSION="6.1.17"
JQUERY_VERSION="3.6.0"
CHARTJS_VERSION="4.5.1"

# Define vendor files: name | url | output path
declare -a VENDORS=(
  "Select2 CSS|https://cdnjs.cloudflare.com/ajax/libs/select2/${SELECT2_VERSION}/css/select2.min.css|src/static/styles/select2.min.css"
  "Select2 JS|https://cdnjs.cloudflare.com/ajax/libs/select2/${SELECT2_VERSION}/js/select2.min.js|src/static/scripts/select2.min.js"
  "jQuery|https://code.jquery.com/jquery-${JQUERY_VERSION}.min.js|src/static/scripts/jquery.min.js"
  "Chart JS|https://cdn.jsdelivr.net/npm/chart.js@${CHARTJS_VERSION}/dist/chart.umd.min.js|src/static/scripts/chart.js"
  "Fullcalendar JS|https://cdn.jsdelivr.net/npm/fullcalendar@${FULLCALENDAR_VERSION}/index.global.min.js|src/static/scripts/calendar.min.js"
)

# Download each vendor file
for vendor in "${VENDORS[@]}"; do
  IFS='|' read -r name url output <<< "$vendor"
  echo "Updating $name..."
  # JTN-534: --retry-all-errors retries write errors too (curl exit 23) which
  # bit us during the JTN-528 sim run. --retry-delay 2 spaces retries to avoid
  # hammering the CDN under flaky connectivity.
  if curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 \
      --connect-timeout 10 --max-time 120 "$url" -o "$output"; then
    echo "  ✓ Downloaded to $output"
  else
    rc=$?
    echo "  ✗ Failed to download $name (curl exit $rc)" >&2
    exit 1
  fi
done

echo "All vendor files updated."
