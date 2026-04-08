#!/bin/bash
# Check that all dependencies use compatible licenses.
# Blocks GPL-3 / AGPL-3 specifically (LGPL and GPL-2 are allowed).
#
# Known GPL-3 exemptions tracked separately for replacement.
# Do NOT add more — see JTN-298 follow-up.
set -e

pip install --quiet pip-licenses
pip-licenses \
  --fail-on='GPL-3.0;AGPL-3.0;GPL-3.0-or-later;AGPL-3.0-or-later;GPL v3;AGPL v3;GPL-3.0-only;AGPL-3.0-only' \
  --format=plain \
  --ignore-packages recurring-ical-events rfc3987
