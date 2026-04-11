#!/usr/bin/env bash
# scripts/cloud_init_clean.sh
# Resets cloud-init state so per-instance modules (runcmd, users, packages)
# re-run on next boot. Use this when you've edited /boot/firmware/user-data
# after the Pi has already booted at least once.
#
# JTN-591: see docs/installation.md for the full explanation.
set -euo pipefail

if ! command -v cloud-init >/dev/null 2>&1; then
  echo "cloud-init is not installed on this system. Nothing to do."
  exit 0
fi

echo "Resetting cloud-init state..."
sudo cloud-init clean --logs
echo
echo "cloud-init state cleared."
echo "  On next boot, cloud-init will re-process /boot/firmware/user-data"
echo "  including any new runcmd entries."
echo
echo "To boot now, run: sudo reboot"
