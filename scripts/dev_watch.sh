#!/usr/bin/env bash
# dev_watch.sh — watch src/static/* and src/templates/ and auto-rebuild.
#
# Behavior
#   - src/static/styles/    → runs `python3 scripts/build_css.py`
#   - src/static/scripts/   → runs `python3 scripts/build_assets.py` (JS bundle)
#   - src/templates/        → logs the change (Flask auto-reloads templates)
#
# One line per rebuild:
#   [2026-04-14T12:34:56] rebuild css (source: _buttons.css)
#
# Ctrl+C exits cleanly. Rapid successive file events are debounced (200ms
# window) so IDE auto-save bursts don't trigger N rebuilds.
#
# Requires the `watchdog` Python package (ships with `watchmedo`). If it's
# missing, the script prints an install hint and exits non-zero.
#
# Works on macOS and Linux. Primary dev platform: macOS.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${SCRIPT_DIR}/.."
cd "${REPO_ROOT}"

# Prefer the repo venv's python if present; fall back to python3 on PATH.
PYTHON="python3"
if [ -x "${REPO_ROOT}/.venv/bin/python" ]; then
  PYTHON="${REPO_ROOT}/.venv/bin/python"
elif [ -x "${REPO_ROOT}/venv/bin/python" ]; then
  PYTHON="${REPO_ROOT}/venv/bin/python"
fi

# Detect watchdog + watchmedo. We shell out to the python above so we pick up
# whatever environment the developer is actually using.
if ! "${PYTHON}" -c "import watchdog" >/dev/null 2>&1; then
  cat >&2 <<'EOF'
error: watchdog is not installed in the active Python environment.

Install it with one of:

  pip install watchdog
  .venv/bin/pip install watchdog

(watchdog is listed in install/requirements-dev.in but is not part of the
compiled lockfile; installing the single package is the quickest fix.)

Then re-run ./scripts/dev_watch.sh
EOF
  exit 1
fi

# Path to the bundled CLI that ships with watchdog.
WATCHMEDO="$(dirname "${PYTHON}")/watchmedo"
if [ ! -x "${WATCHMEDO}" ]; then
  # Fall back to running it via `python -m watchdog.watchmedo`. This works on
  # distros that don't install the CLI shim.
  WATCHMEDO_RUN=("${PYTHON}" -m watchdog.watchmedo)
else
  WATCHMEDO_RUN=("${WATCHMEDO}")
fi

STYLES_DIR="${REPO_ROOT}/src/static/styles"
SCRIPTS_DIR="${REPO_ROOT}/src/static/scripts"
TEMPLATES_DIR="${REPO_ROOT}/src/templates"

for d in "${STYLES_DIR}" "${SCRIPTS_DIR}" "${TEMPLATES_DIR}"; do
  if [ ! -d "${d}" ]; then
    echo "error: watched directory not found: ${d}" >&2
    exit 1
  fi
done

# Dispatcher script — called by watchmedo with the event type and path. This
# is what debounces + routes + logs.
DISPATCHER="${SCRIPT_DIR}/_dev_watch_dispatch.py"
if [ ! -f "${DISPATCHER}" ]; then
  echo "error: missing dispatcher helper: ${DISPATCHER}" >&2
  exit 1
fi

echo "dev_watch: watching styles/, scripts/, templates/ (Ctrl+C to exit)"

# Trap Ctrl+C so the message is clean rather than a traceback.
trap 'echo ""; echo "dev_watch: stopped."; exit 0' INT TERM

# --recursive so nested partials/macros are covered. --ignore-patterns avoids
# rebuild loops from the generated main.css / dist bundles.
exec "${WATCHMEDO_RUN[@]}" shell-command \
  --patterns="*.css;*.js;*.html" \
  --ignore-patterns="*/main.css;*/dist/*;*/__pycache__/*" \
  --ignore-directories \
  --recursive \
  --command="${PYTHON} ${DISPATCHER} \${watch_event_type} \${watch_src_path}" \
  "${STYLES_DIR}" "${SCRIPTS_DIR}" "${TEMPLATES_DIR}"
