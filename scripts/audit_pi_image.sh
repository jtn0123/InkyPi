#!/usr/bin/env bash
# audit_pi_image.sh — assert a built Pi image is fit to ship.
#
# Reads the image's filesystems directly with debugfs, so it needs no root and
# no loop device. Runs in seconds, unlike a rebuild.
#
#   ./scripts/audit_pi_image.sh build/inkypi-1.0.2-pi-zero-2-w.img.xz
#   ./scripts/audit_pi_image.sh some.img
#
# Exists because v1.0.2 shipped with the build's own chroot scaffolding still
# inside it — the systemctl/raspi-config stubs on PATH and the builder's
# resolv.conf — and the result could neither join wifi nor resolve DNS. Nothing
# in the pipeline looked at the contents of what it was about to publish.
set -euo pipefail

IMG="${1:-}"
[ -n "${IMG}" ] || { echo "Usage: audit_pi_image.sh <image.img|image.img.xz>" >&2; exit 2; }
[ -f "${IMG}" ] || { echo "ERROR: no such file: ${IMG}" >&2; exit 2; }

command -v debugfs >/dev/null 2>&1 || {
    echo "ERROR: debugfs not found (package e2fsprogs)" >&2; exit 2; }

WORK=""
# shellcheck disable=SC2317 # only invoked indirectly via `trap ... EXIT` below
cleanup() { [ -n "${WORK}" ] && rm -rf "${WORK}"; }
trap cleanup EXIT

case "${IMG}" in
    *.xz)
        WORK=$(mktemp -d)
        echo "Decompressing $(basename "${IMG}") ..."
        xz -dc -T 0 "${IMG}" > "${WORK}/image.img"
        IMG="${WORK}/image.img"
        ;;
esac

# Partition offsets, in bytes. fdisk reads a plain file without root.
# fdisk right-aligns the Start column, so rows can begin with spaces — match on
# the field being numeric rather than on the line starting with a digit.
read -r BOOT_OFF ROOT_OFF <<<"$(
    fdisk -l -o Start,Type "${IMG}" 2>/dev/null \
        | awk '$1 ~ /^[0-9]+$/ {printf "%d ", $1 * 512}'
)"
if [ -z "${ROOT_OFF:-}" ] || [ "${ROOT_OFF}" -le 0 ]; then
    echo "ERROR: could not read partition table from ${IMG}" >&2
    exit 2
fi

FS="${IMG}?offset=${ROOT_OFF}"
d() { debugfs -R "$1" "${FS}" 2>/dev/null; }

PASS=0
FAIL=0
ok()   { printf '  \033[32mPASS\033[0m  %s\n' "$1"; PASS=$((PASS + 1)); }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; FAIL=$((FAIL + 1)); }

# debugfs writes its "File not found" to stderr and nothing to stdout, so a
# missing path yields no Inode line. Matching on Inode rather than on empty
# output means a debugfs error cannot be mistaken for a clean result.
absent() { ! d "stat $1" | grep -q "Inode:"; }

echo ""
echo "Auditing $(basename "${1}")  (rootfs at offset ${ROOT_OFF})"
echo ""

echo "Shipped artifact size:"
MAX_SHIPPED_BYTES=943718400
case "$1" in
    *.xz)
        SHIPPED_BYTES=$(stat -c %s "$1")
        if [ "${SHIPPED_BYTES}" -gt "${MAX_SHIPPED_BYTES}" ]; then
            bad "$(basename "$1") is $(numfmt --to=iec "${SHIPPED_BYTES}"), over the $(numfmt --to=iec "${MAX_SHIPPED_BYTES}") ceiling — unexpected bloat?"
        else
            ok "$(basename "$1") is $(numfmt --to=iec "${SHIPPED_BYTES}"), under the $(numfmt --to=iec "${MAX_SHIPPED_BYTES}") ceiling"
        fi
        ;;
    *)
        echo "  (skipped — not a .img.xz)"
        ;;
esac
echo ""

echo "Build scaffolding must not ship:"

for stub in /usr/local/sbin/raspi-config /usr/local/sbin/systemctl; do
    # These shadow the real binaries: /usr/local/sbin precedes both /usr/sbin
    # and /usr/bin in root's PATH, and raspi-config lives in /usr/bin. Stubbed
    # out it never sets the wifi regulatory domain, so the radio stays
    # rfkill-blocked and the Pi joins nothing.
    if absent "${stub}"; then ok "${stub} removed"; else bad "${stub} STILL PRESENT — shadows the real binary on PATH"; fi
done

if absent /usr/bin/qemu-aarch64-static; then ok "qemu-aarch64-static removed"; else bad "qemu-aarch64-static still present (~10 MB of dead weight)"; fi

echo ""
echo "Host configuration must be the image's own:"

RESOLV="$(d "cat /etc/resolv.conf" || true)"
if printf '%s' "${RESOLV}" | grep -qE '127\.0\.0\.53|cloudapp\.net'; then
    bad "/etc/resolv.conf carries the builder's DNS — Pi OS Lite runs no systemd-resolved, so nothing resolves"
else
    ok "/etc/resolv.conf is not the builder's"
fi

MID_SIZE="$(d "stat /etc/machine-id" | sed -n 's/.*Size: \([0-9]*\).*/\1/p' | head -1)"
if [ "${MID_SIZE:-0}" -eq 0 ]; then
    ok "/etc/machine-id blank (each card generates its own)"
else
    bad "/etc/machine-id populated (${MID_SIZE} bytes) — every flashed card shares one identity"
fi

echo ""
echo "First-boot customisation must still work:"

# Pi OS Trixie dropped the old custom.toml/raspberrypi-sys-mods firstboot
# mechanism entirely — cmdline.txt no longer carries an init= hook for it, and
# neither /usr/lib/raspberrypi-sys-mods/init_config nor python3-toml ship in
# the image any more. First-boot customisation is now cloud-init: the boot
# partition ships a stock user-data template (edited by hand, or rewritten by
# Pi Imager's "advanced options"), applied by the cloud-init package via a
# systemd generator rather than a static enable symlink.
#
# The boot partition still ships that user-data template; grep the raw FAT
# region rather than implementing a FAT reader (small files there are
# contiguous). grep -c rather than -q: with -q grep exits on the first match,
# dd dies of SIGPIPE, and pipefail turns that into a false "not found".
USERDATA_HITS=$(dd if="${IMG}" bs=1M skip=$((BOOT_OFF / 1048576)) count=512 status=none 2>/dev/null \
     | grep -ac '#cloud-config' || true)
if [ "${USERDATA_HITS:-0}" -gt 0 ]; then
    ok "boot partition still ships the cloud-init user-data template"
else
    bad "cloud-init user-data template missing from the boot partition — Pi Imager's advanced options will have nothing to rewrite"
fi

if absent /etc/cloud/cloud.cfg; then
    bad "/etc/cloud/cloud.cfg missing — cloud-init cannot apply user-data"
else
    ok "cloud-init config present (user-data will be applied)"
fi

# sshswitch.service (raspberrypi-sys-mods) only enables+starts ssh if this
# marker file exists on the boot partition — cloud-init/Imager never create
# it, so without it sshd never starts. Matching on the padded 8.3 FAT
# directory entry ("SSH" + 8 spaces, no extension) rather than a bare "ssh"
# substring — that string shows up incidentally elsewhere on this partition
# (ssh_config, doc text) often enough to make a plain substring match noisy.
SSH_MARKER_HITS=$(dd if="${IMG}" bs=1M skip=$((BOOT_OFF / 1048576)) count=512 status=none 2>/dev/null \
     | grep -ac 'SSH        ' || true)
if [ "${SSH_MARKER_HITS:-0}" -gt 0 ]; then
    ok "boot partition ships the /boot/firmware/ssh marker (sshswitch will enable ssh, belt-and-suspenders)"
else
    bad "/boot/firmware/ssh marker missing (harmless on its own, but check the runcmd below)"
fi

# The marker/sshswitch path above was found unreliable on real Trixie
# hardware. Primary mechanism is a live cloud-init runcmd in user-data —
# the same one Raspberry Pi Imager itself writes for official images. Grep
# for the exact live line rather than just "runcmd" or "ssh", since the
# stock template ships a commented-out `#runcmd:` example that would
# false-positive a substring match.
RUNCMD_SSH_HITS=$(dd if="${IMG}" bs=1M skip=$((BOOT_OFF / 1048576)) count=512 status=none 2>/dev/null \
     | grep -ac -- '- \[ systemctl, enable, --now, ssh \]' || true)
if [ "${RUNCMD_SSH_HITS:-0}" -gt 0 ]; then
    ok "user-data carries a live runcmd enabling ssh (unconditional, matches Imager's own mechanism)"
else
    bad "user-data's runcmd enabling ssh is missing or still commented out — sshd will not listen on first boot"
fi

# Confirmed on real hardware: regenerate_ssh_host_keys.service's
# ConditionFirstBoot=yes can lose a race against systemd-machine-id-commit
# and silently skip, leaving sshd with no host keys to bind — the marker and
# runcmd above only ask ssh.service to start, they don't guarantee it can.
# This drop-in is what actually makes that reliable.
if d "cat /etc/systemd/system/ssh.service.d/inkypi-hostkeys.conf" | grep -qxF -- 'ExecStartPre=/usr/bin/ssh-keygen -A'; then
    ok "ssh.service.d drop-in generates its own host keys (independent of regenerate_ssh_host_keys.service)"
else
    bad "ssh.service.d hostkey drop-in missing — sshd will fail to start if regenerate_ssh_host_keys.service ever skips (confirmed to happen on real hardware)"
fi

# cloud-init enables its own units via this generator at boot, not via a
# static multi-user.target.wants symlink — so that's what to check for here.
if absent /usr/lib/systemd/system-generators/cloud-init-generator; then
    bad "cloud-init-generator missing — nothing enables cloud-init's units at boot"
else
    ok "cloud-init-generator present (enables cloud-init units at boot)"
fi

# Pi OS ships raspi-config in /usr/bin, not /usr/sbin. /usr/local/sbin still
# precedes it in root's PATH, which is why the stub shadowed it.
if absent /usr/bin/raspi-config; then
    bad "the real /usr/bin/raspi-config is missing"
else
    ok "real raspi-config present"
fi

echo ""
echo "The installed app must be able to start:"

# install.sh symlinks /usr/local/inkypi/src at the source checkout rather than
# copying it, so the checkout is PART OF THE INSTALL, not build residue. A
# cleanup pass deleted it as if it were leftovers and the service then died on
# every boot with:
#   realpath: /usr/local/inkypi/src/inkypi.py: No such file or directory
LINK_DEST="$(d "stat /usr/local/inkypi/src" | sed -n 's/.*Fast link dest: "\(.*\)".*/\1/p' | head -1)"
if [ -z "${LINK_DEST}" ]; then
    bad "/usr/local/inkypi/src is missing"
else
    # Lexical normalisation only — the path lives inside the image, not here.
    RESOLVED="$(realpath -m "${LINK_DEST}")"
    if absent "${RESOLVED}/inkypi.py"; then
        bad "/usr/local/inkypi/src -> ${LINK_DEST} is DANGLING (no inkypi.py at ${RESOLVED})"
    else
        ok "/usr/local/inkypi/src resolves to a real checkout (${RESOLVED})"
    fi
fi

# The Inky driver calls inky.auto.auto(), which reads the HAT EEPROM over I2C
# at 0x50. dtparam=i2c_arm=on alone does not create /dev/i2c-1 — that needs the
# i2c-dev module, normally registered by `raspi-config nonint do_i2c 0`, which
# is stubbed out during the image build. Without it the panel is never driven.
if d "cat /etc/modules" | grep -qx "i2c-dev"; then
    ok "i2c-dev registered in /etc/modules (Inky EEPROM will be readable)"
else
    bad "i2c-dev not in /etc/modules — /dev/i2c-1 will not exist and inky.auto() fails with 'No EEPROM detected'"
fi

# Pi OS ships NetworkManager with WirelessEnabled=false in its persisted
# state file — confirmed on real hardware to mean the wifi radio never comes
# up at all, independent of any SSID/password/regulatory-domain setting.
# build_pi_image.sh flips this; verify it stuck.
if d "cat /var/lib/NetworkManager/NetworkManager.state" | grep -qx "WirelessEnabled=true"; then
    ok "NetworkManager WirelessEnabled=true (wifi radio enabled by default)"
else
    bad "NetworkManager.state does not have WirelessEnabled=true — wifi radio will not come up on boot"
fi

CFG_DIR_LS="$(d "ls /opt/inkypi-src/src/config" | tr -s ' \n' '\n')"
if printf '%s' "${CFG_DIR_LS}" | grep -qx "device.json"; then
    ok "device.json provisioned"
else
    bad "device.json missing — install.sh generates it from install/config_base"
fi

if absent /usr/local/inkypi/venv_inkypi/bin/python; then
    bad "venv interpreter missing at /usr/local/inkypi/venv_inkypi/bin/python"
else
    ok "venv interpreter present"
fi

if absent /usr/local/bin/inkypi; then
    bad "/usr/local/bin/inkypi launcher missing (ExecStart of inkypi.service)"
else
    ok "inkypi launcher present"
fi

if [ -n "$(d "ls /etc/systemd/system/multi-user.target.wants" | tr -s ' \n' '\n' | grep -x inkypi.service || true)" ]; then
    ok "inkypi.service enabled"
else
    bad "inkypi.service not enabled — it will not start on boot"
fi

echo ""
if [ "${FAIL}" -eq 0 ]; then
    echo "OK — ${PASS} checks passed, image is fit to ship."
    exit 0
fi
echo "FAILED — ${FAIL} problem(s) found, ${PASS} passed. This image should not ship."
exit 1
