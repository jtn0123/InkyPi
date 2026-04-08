#!/bin/bash
# Check that all dependencies use compatible licenses.
# Fails if any GPL or AGPL licenses are detected.
set -e

pip install --quiet pip-licenses
pip-licenses --fail-on='GPL;AGPL' --partial-match --format=plain
