#!/usr/bin/env bash
# Run a Python dev tool for a pre-commit hook: scripts/precommit_tool.sh <tool> [args...]
#
# Uses the repo's .venv when it has the tool, so the hook runs the version
# pinned in install/requirements-dev.txt (the one CI uses) rather than
# whatever pre-commit would install on its own. Otherwise falls back to the
# tool on PATH, which in CI is the same pinned install.
set -euo pipefail

tool="${1:?usage: precommit_tool.sh <tool> [args...]}"
shift

root="$(git rev-parse --show-toplevel)"
if [[ -x "${root}/.venv/bin/${tool}" ]]; then
    exec "${root}/.venv/bin/${tool}" "$@"
fi
# A git worktree has no .venv of its own; use the main checkout's.
common="$(git rev-parse --path-format=absolute --git-common-dir)"
main_root="$(dirname "${common}")"
if [[ -x "${main_root}/.venv/bin/${tool}" ]]; then
    exec "${main_root}/.venv/bin/${tool}" "$@"
fi
exec "${tool}" "$@"
