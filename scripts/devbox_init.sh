#!/usr/bin/env bash
# Devbox runs init hooks with /bin/sh; keep Bash setup in an explicit child.
set -euo pipefail
cd "${DEVBOX_PROJECT_ROOT:?Devbox project root is required}"
# shellcheck source=scripts/venv.sh
source scripts/venv.sh
shopt -s nullglob
calendar_files=(src/static/scripts/calendar*)
select2_files=(src/static/styles/select2*)
if [[ ${#calendar_files[@]} -eq 0 || ${#select2_files[@]} -eq 0 ]]; then
    bash install/update_vendors.sh
fi
if [[ "$(uname -s)" == Darwin ]] && ! command -v chrome >/dev/null; then
    if [[ -d '/Applications/Google Chrome.app' ]]; then
        chrome_shim="${DEVBOX_PROJECT_ROOT}/.devbox/virtenv/runx/bin/chrome"
        mkdir -p "$(dirname "$chrome_shim")"
        cat > "$chrome_shim" <<'SHIM'
#!/usr/bin/env bash
exec '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' "$@"
SHIM
        chmod +x "$chrome_shim"
    else
        printf 'Install Google Chrome in /Applications for macOS rendering.\n'
    fi
fi
printf '\nInkyPi environment ready. Run: devbox run dev\nOpen: http://localhost:8080\n'
