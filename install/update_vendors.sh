#!/usr/bin/env bash

set -euo pipefail

# JTN-615: vendor file destinations are specified relative to the repo root
# (e.g. `src/static/scripts/chart.js`), so the script MUST run with cwd
# set to the repo root regardless of how install.sh invokes it. install.sh
# calls us via `bash "$SCRIPT_DIR/update_vendors.sh"`, which does not change
# cwd — so we were writing to $PWD/src/static/... which only existed when the
# user happened to invoke install.sh from the repo root. In CI (Dockerfile
# WORKDIR = /InkyPi/install), the relative path resolved to a non-existent
# directory and every curl call failed with exit 23 ("Failure writing output
# to destination"). Anchor cwd to the repo root here so relative paths always
# resolve correctly.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# Versions
FULLCALENDAR_VERSION="6.1.22"
CHARTJS_VERSION="4.6.1"
SWAGGER_UI_VERSION="5.35.0"

# Define vendor files: name | url | output path | sha256 of the file.
# E4: each download must match its pinned hash, so a compromised or
# misconfigured CDN can't swap in different code. To bump a version, take the
# new hash from the file inside the package's npm tarball (whose sha512
# integrity the registry publishes), not only from the CDN's copy.
declare -a VENDORS=(
  "Chart JS|https://cdn.jsdelivr.net/npm/chart.js@${CHARTJS_VERSION}/dist/chart.umd.min.js|src/static/scripts/chart.js|87364cc2b2a76a6684929e7d6b80b18a897794db38400caff1fcf1791c6925d2"
  "Fullcalendar JS|https://cdn.jsdelivr.net/npm/fullcalendar@${FULLCALENDAR_VERSION}/index.global.min.js|src/static/scripts/calendar.min.js|65f927f1802cb35428b9c5e2a8d2276633880a89ee5ea5f9a7727f79892786ea"
  "Swagger UI CSS|https://cdn.jsdelivr.net/npm/swagger-ui-dist@${SWAGGER_UI_VERSION}/swagger-ui.css|src/static/vendor/swagger-ui/swagger-ui.css|5ed08757e53da3e026d6cbecc61fe5d43585c9560b302d534ad56692519a273d"
  "Swagger UI JS|https://cdn.jsdelivr.net/npm/swagger-ui-dist@${SWAGGER_UI_VERSION}/swagger-ui-bundle.js|src/static/vendor/swagger-ui/swagger-ui-bundle.js|e6a898692f2d768e807c3ba4626068a69a2c5dd960dd6c76f3e4d3a3de180af2"
)

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

# Download each vendor file to a temporary name next to its destination, check
# its hash, and only then move it into place. A failed download or a mismatch
# leaves the previous copy untouched.
for vendor in "${VENDORS[@]}"; do
  IFS='|' read -r name url output expected_sha <<< "$vendor"
  if [[ ! "$expected_sha" =~ ^[0-9a-f]{64}$ ]]; then
    echo "  ✗ $name has no pinned sha256 in update_vendors.sh" >&2
    exit 1
  fi
  echo "Updating $name..."
  # Swagger UI's folder is git-ignored, so a fresh checkout doesn't have it.
  mkdir -p "$(dirname "$output")"
  tmp="$(mktemp "${output}.download.XXXXXX")"
  # JTN-534: --retry-all-errors retries write errors too (curl exit 23) which
  # bit us during the JTN-528 sim run. --retry-delay 2 spaces retries to avoid
  # hammering the CDN under flaky connectivity.
  if curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 \
      --connect-timeout 10 --max-time 120 "$url" -o "$tmp"; then
    :
  else
    rc=$?
    rm -f "$tmp"
    echo "  ✗ Failed to download $name (curl exit $rc)" >&2
    exit 1
  fi
  actual_sha="$(sha256_of "$tmp")"
  if [ "$actual_sha" != "$expected_sha" ]; then
    rm -f "$tmp"
    echo "  ✗ $name failed its hash check: expected $expected_sha, got $actual_sha" >&2
    exit 1
  fi
  chmod 644 "$tmp"
  mv -f "$tmp" "$output"
  echo "  ✓ Downloaded and verified $output"
done

echo "All vendor files updated."
