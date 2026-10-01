#!/usr/bin/env bash
set -euo pipefail
chromium --version
chromium --version | grep -F '154.0.8037.57'
SKIP_UI=1 SKIP_A11Y=1 python -m pytest -q tests/plugins/test_countdown.py
