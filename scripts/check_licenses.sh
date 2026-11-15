#!/bin/bash
# Check that all dependencies use compatible licenses.
# Blocks GPL-3 / AGPL-3 specifically (LGPL and GPL-2 are allowed).
# Partial matching is intentionally OFF so LGPL and GPL-2-or-later pass.
#
# Known GPL-3 exemptions tracked separately for replacement.
# Do NOT add more — see JTN-298 follow-up.
#
# pip-licenses comes from install/requirements-dev.txt, which pins it to an
# exact version with hashes, so this script installs nothing. It audits the
# environment of the `python` on PATH: run it from the dev virtualenv, as
# CI's lint job does.
set -euo pipefail

if ! python -m piplicenses --version >/dev/null 2>&1; then
  python_path="$(command -v python || true)"
  echo "pip-licenses is not installed for ${python_path:-python (none on PATH)}." >&2
  echo "Install the dev lockfile first: pip install --require-hashes -r install/requirements-dev.txt" >&2
  exit 1
fi

python -m piplicenses \
  --fail-on='GPL-3.0;AGPL-3.0;GPL-3.0-or-later;AGPL-3.0-or-later;GPL v3;AGPL v3;GPL-3.0-only;AGPL-3.0-only' \
  --format=plain \
  --ignore-packages recurring-ical-events
