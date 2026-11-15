#!/usr/bin/env bash
# Syntax-check and lint every tracked shell script.
#
# The script list is discovered, not hand-kept: every tracked *.sh file plus
# every extension-less tracked file with a bash or sh shebang (install/inkypi,
# install/cli/inkypi-plugin). A new script is covered the moment it is
# committed.
#
# Each script gets `bash -n`, then all of them go through shellcheck at its
# default (strictest) severity. scripts/lint.sh runs this, so CI's lint job
# and a local lint run check the same files the same way.
#
# shellcheck is required when CI is set. Locally a missing shellcheck is a
# warning, and the bash -n pass still runs.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}" || exit 1

is_shell_script() {
    local path="$1"
    local name="${path##*/}"
    local first_line=""

    case "${name}" in
        *.sh) return 0 ;;
        *.*) return 1 ;;
    esac
    [[ -f "${path}" ]] || return 1
    IFS= read -r first_line < "${path}" || [[ -n "${first_line}" ]] || return 1
    [[ "${first_line}" =~ ^#!.*[/[:space:]](ba)?sh([[:space:]]|$) ]]
}

if ! tracked_output="$(git ls-files)"; then
    echo "❌ check_shell.sh: git ls-files failed; run it from a git checkout." >&2
    exit 1
fi

scripts=()
while IFS= read -r path; do
    [[ -n "${path}" ]] || continue
    if is_shell_script "${path}"; then
        scripts+=("${path}")
    fi
done <<< "${tracked_output}"

if [[ ${#scripts[@]} -eq 0 ]]; then
    echo "❌ check_shell.sh: found no shell scripts; discovery is broken." >&2
    exit 1
fi

echo "Checking ${#scripts[@]} shell scripts..."

syntax_exit=0
for path in "${scripts[@]}"; do
    if ! bash -n "${path}"; then
        echo "❌ bash -n failed: ${path}"
        syntax_exit=1
    fi
done
if [[ ${syntax_exit} -eq 0 ]]; then
    echo "✅ bash -n passed"
fi

shellcheck_exit=0
if command -v shellcheck >/dev/null 2>&1; then
    shellcheck --version | sed -n 's/^version: /shellcheck /p'
    if shellcheck "${scripts[@]}"; then
        echo "✅ shellcheck passed"
    else
        shellcheck_exit=1
        echo "❌ shellcheck found issues"
    fi
elif [[ -n "${CI:-}" ]]; then
    echo "❌ shellcheck not found — install it in the CI image."
    shellcheck_exit=1
else
    echo "⚠️  shellcheck not found — skipping (install via: brew install shellcheck / apt install shellcheck)"
fi

if [[ ${syntax_exit} -ne 0 || ${shellcheck_exit} -ne 0 ]]; then
    exit 1
fi
exit 0
