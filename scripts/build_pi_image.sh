#!/usr/bin/env bash
# build_pi_image.sh — build the pre-installed InkyPi .img.xz for the Pi Zero 2 W.
#
# Used by the `build-image` job in .github/workflows/build-pi-image.yml
# (JTN-533) and runnable by hand. The workflow calls this script rather than
# repeating the steps inline, so a local build exercises the same code CI does
# — testing a copy would prove nothing about the workflow.
#
#   sudo ./scripts/build_pi_image.sh --tag v1.0.2
#   sudo ./scripts/build_pi_image.sh --tag v1.0.2 --fast   # skip slow xz/zerofill
#   ./scripts/build_pi_image.sh --help
#
# Needs root (loop-mounting and chrooting the image), binfmt registration for
# arm64 (qemu-user-static), and ~12 GB of free disk. Expect ~20-40 minutes:
# install.sh runs fully emulated inside the image.
#
# Everything staged to make the chroot work is removed again before packaging.
# v1.0.2 shipped with the systemctl/raspi-config stubs still on PATH and the
# builder's resolv.conf in place, producing an image that could neither join
# wifi nor resolve DNS; see remove_scaffolding() below.
set -euo pipefail

# --- pins ---------------------------------------------------------------------
# Kept in sync with the PIN POINT block in build-pi-image.yml. The workflow
# exports these, so its values win; the defaults are for local runs.
PI_OS_IMAGE_URL="${PI_OS_IMAGE_URL:-https://downloads.raspberrypi.org/raspios_lite_arm64/images/raspios_lite_arm64-2026-06-19/2026-06-18-raspios-trixie-arm64-lite.img.xz}"
PI_OS_IMAGE_SHA256="${PI_OS_IMAGE_SHA256:-acff736ca7945e3b305f07cda4abdb870910e12634991da69783611756e381b3}"
PI_OS_IMAGE_FILENAME="${PI_OS_IMAGE_FILENAME:-2026-06-18-raspios-trixie-arm64-lite.img.xz}"
PISHRINK_TAG="${PISHRINK_TAG:-v26.03.16}"
PISHRINK_SHA256="${PISHRINK_SHA256:-71026f0c02ac099e588a3eb8f70760c1b680aa8ea3acde61a0141fbaeb68c777}"

SRC_REPO="${INKYPI_SRC_REPO:-https://github.com/jtn0123/InkyPi.git}"
BUILD_DIR="${BUILD_DIR:-build}"
MNT="${MNT:-/mnt/pi-root}"
TAG=""
FAST=0

usage() {
    cat <<'USAGE'
Usage: sudo build_pi_image.sh --tag <release-tag> [options]

Builds inkypi-<version>-pi-zero-2-w.img.xz from the pinned Pi OS Lite base.

Options:
  -t, --tag TAG      Release tag to build from, e.g. v1.0.2 (required)
  -r, --repo URL     Git URL to clone inside the image
                     (default: $INKYPI_SRC_REPO or the cartagena fork)
  -b, --builddir DIR Work directory (default: build)
      --fast         xz -0 instead of -9 and skip the zero-fill. Much faster,
                     much larger output. For iterating, never for a release.
  -h, --help         This message

Requires root, qemu-user-static with arm64 binfmt registered, and ~12 GB free.
USAGE
}

while [ $# -gt 0 ]; do
    case "$1" in
        -t|--tag)      TAG="$2"; shift 2 ;;
        -r|--repo)     SRC_REPO="$2"; shift 2 ;;
        -b|--builddir) BUILD_DIR="$2"; shift 2 ;;
        --fast)        FAST=1; shift ;;
        -h|--help)     usage; exit 0 ;;
        *)             echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

[ -n "${TAG}" ] || { echo "ERROR: --tag is required" >&2; usage >&2; exit 2; }
[ "$(id -u)" -eq 0 ] || { echo "ERROR: must run as root (loop-mount + chroot)" >&2; exit 2; }

VERSION="${TAG#v}"

for tool in curl xz truncate parted losetup e2fsck resize2fs chroot sha256sum; do
    command -v "${tool}" >/dev/null 2>&1 || {
        echo "ERROR: ${tool} not found. On Debian/Ubuntu:" >&2
        echo "  apt-get install -y qemu-user-static binfmt-support parted \\" >&2
        echo "      util-linux dosfstools e2fsprogs xz-utils curl ca-certificates" >&2
        exit 2
    }
done
# Without binfmt the chroot cannot execute the image's arm64 binaries, and the
# first command inside it fails with a confusing "Exec format error".
[ -e /proc/sys/fs/binfmt_misc/qemu-aarch64 ] || {
    echo "ERROR: no arm64 binfmt handler registered." >&2
    echo "  apt-get install -y qemu-user-static binfmt-support" >&2
    echo "  (or: docker run --privileged --rm tonistiigi/binfmt --install arm64)" >&2
    exit 2
}
command -v qemu-aarch64-static >/dev/null 2>&1 || {
    echo "ERROR: qemu-aarch64-static not found (package qemu-user-static)" >&2
    exit 2
}

banner() {
    echo ""
    echo "======================================================================"
    echo "  $1"
    echo "======================================================================"
}

LOOP=""
cleanup() {
    # Ordering matters: nested mounts before the ones they sit inside, or the
    # loop device stays busy and the image is left mounted.
    umount "${MNT}/dev/pts" 2>/dev/null || true
    umount "${MNT}/dev" 2>/dev/null || true
    umount "${MNT}/proc" 2>/dev/null || true
    umount "${MNT}/sys" 2>/dev/null || true
    umount "${MNT}/boot/firmware" 2>/dev/null || true
    umount "${MNT}" 2>/dev/null || true
    [ -n "${LOOP}" ] && losetup -d "${LOOP}" 2>/dev/null || true
}
trap cleanup EXIT

mkdir -p "${BUILD_DIR}"
cd "${BUILD_DIR}"

# --- base image ---------------------------------------------------------------
banner "Fetching pinned Pi OS Lite base"
if [ ! -f "${PI_OS_IMAGE_FILENAME}" ]; then
    curl -fsSL -o "${PI_OS_IMAGE_FILENAME}" "${PI_OS_IMAGE_URL}"
else
    echo "Reusing ${PI_OS_IMAGE_FILENAME}"
fi
echo "${PI_OS_IMAGE_SHA256}  ${PI_OS_IMAGE_FILENAME}" > base.sha256
sha256sum -c base.sha256

BASE_IMG="${PI_OS_IMAGE_FILENAME%.xz}"
rm -f "${BASE_IMG}"
xz -dk -T 0 "${PI_OS_IMAGE_FILENAME}"

# --- room to install ----------------------------------------------------------
banner "Growing image for the install"
# Pi OS Lite is ~2.5 GB; install.sh adds ~1 GB of venv + apt packages. 3 GB of
# slack keeps pip/apt from hitting ENOSPC. pishrink reclaims it before shipping.
truncate -s +3G "${BASE_IMG}"
parted --script "${BASE_IMG}" resizepart 2 100%

LOOP=$(losetup --show -Pf "${BASE_IMG}")
echo "Loop device: ${LOOP}"
partprobe "${LOOP}" || true
e2fsck -f -y "${LOOP}p2" || true
resize2fs "${LOOP}p2"
mkdir -p "${MNT}"
mount "${LOOP}p2" "${MNT}"
mkdir -p "${MNT}/boot/firmware"
mount "${LOOP}p1" "${MNT}/boot/firmware"
df -h "${MNT}" "${MNT}/boot/firmware"

# --- chroot plumbing ----------------------------------------------------------
banner "Staging chroot"
cp /usr/bin/qemu-aarch64-static "${MNT}/usr/bin/"
mount --bind /dev     "${MNT}/dev"
mount --bind /dev/pts "${MNT}/dev/pts"
mount --bind /proc    "${MNT}/proc"
mount --bind /sys     "${MNT}/sys"
# Keep the image's own resolv.conf — on Pi OS it is a symlink into
# NetworkManager's runtime dir. Restored by remove_scaffolding().
cp -a "${MNT}/etc/resolv.conf" "${MNT}/etc/resolv.conf.build-orig"
cp --remove-destination /etc/resolv.conf "${MNT}/etc/resolv.conf"

# install.sh calls raspi-config and `systemctl start`, neither of which means
# anything in an offline chroot. Shadow them on PATH for the duration only —
# /usr/local/sbin sorts before /usr/sbin. These MUST be removed again before
# packaging; see remove_scaffolding().
STUB_DIR="${MNT}/usr/local/sbin"
mkdir -p "${STUB_DIR}"
cat > "${STUB_DIR}/raspi-config" <<'STUB'
#!/bin/sh
echo "[chroot stub] raspi-config $* — no-op (real raspi-config runs on first boot)"
exit 0
STUB
cat > "${STUB_DIR}/systemctl" <<'STUB'
#!/bin/sh
case "$1" in
  start|stop|restart|reload|is-active|is-enabled|status)
    echo "[chroot stub] systemctl $* — deferred to first boot"
    exit 0
    ;;
  *)
    exec /bin/systemctl "$@"
    ;;
esac
STUB
chmod +x "${STUB_DIR}/raspi-config" "${STUB_DIR}/systemctl"

# --- install ------------------------------------------------------------------
banner "Running install.sh inside the image (emulated — this is the slow part)"
# stdin comes from /dev/null so the build cannot block on a prompt.
#
# install.sh ends with `read -r -p "Would you like to restart ... [Y/N]"`, and
# it sets no `set -e`, so at EOF read simply returns non-zero with an empty
# answer, install.sh takes its "Unknown input" branch and exits 0. GitHub
# Actions happens to give every step /dev/null on stdin, so CI has always
# sailed past this prompt by accident. Run the same build from a terminal and
# it blocks forever. Redirect explicitly so both behave the same way for the
# same reason.
#
# Note INKYPI_CI_IMAGE_BUILD is *not* what makes this work: nothing in
# install/ or src/ reads that variable. It is inherited from the original
# workflow and kept only as a marker for anything that may want it later — do
# not rely on it to suppress prompts.
chroot "${MNT}" /usr/bin/env \
    PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    DEBIAN_FRONTEND=noninteractive \
    INKYPI_CI_IMAGE_BUILD=1 \
    /bin/bash -euxo pipefail -c "
      apt-get update
      apt-get install -y --no-install-recommends git ca-certificates
      rm -rf /opt/inkypi-src
      git clone --branch '${TAG}' --depth 1 '${SRC_REPO}' /opt/inkypi-src
      cd /opt/inkypi-src/install
      bash ./install.sh
    " < /dev/null

# --- redo what the stubbed raspi-config swallowed ---------------------------
# install.sh enables the buses two ways: it seds config.txt (which works in a
# chroot) and it calls `raspi-config nonint do_spi 0` / `do_i2c 0`. Both
# raspi-config calls hit the stub above and did nothing.
#
# That only matters for I2C. dtparam=spi=on is enough for spidev to appear on
# its own, but /dev/i2c-1 needs the i2c-dev module, and adding it to
# /etc/modules is precisely the part raspi-config would have done. Without it
# the bus never comes up, and the Inky driver — which reads the HAT's EEPROM
# over I2C at 0x50 to identify the panel — fails with
#     RuntimeError: No EEPROM detected! You must manually initialise your Inky board.
# so the display is never driven at all.
banner "Re-applying what the raspi-config stub swallowed"
if ! grep -qxF 'i2c-dev' "${MNT}/etc/modules"; then
    echo 'i2c-dev' >> "${MNT}/etc/modules"
fi
grep -qxF 'i2c-dev' "${MNT}/etc/modules"
echo "i2c-dev registered in /etc/modules"

# --- unblock wifi: NetworkManager ships it disabled by default -------------
# Confirmed by inspecting the pristine Trixie base image directly: it ships
# /var/lib/NetworkManager/NetworkManager.state containing exactly
# "[main]\nWirelessEnabled=false". Per NetworkManager's own documentation,
# writing WirelessEnabled also updates the kernel rfkill soft-block state for
# wifi (networkmanager.dev/docs/rfkill/) — so this one persisted flag, wholly
# independent of any regulatory-domain/country setting, is why a freshly
# flashed device never joins any network even with correct SSID/password:
# NetworkManager refuses to even bring the radio up. Real-hardware testing
# hit exactly this (service started, e-paper refreshed, wifi never came up).
#
# This is a deliberate InkyPi override of Pi OS's conservative
# ship-wifi-disabled default: the world/00 regulatory domain still applies
# as a conservative safety net (this does not touch regulatory-domain), and
# InkyPi's headless deployment has no way to surface Pi OS's own
# "wifi blocked, run raspi-config" login warning to a user who can't get a
# shell in the first place. Revisit if this default ever needs reconsidering.
banner "Enabling wifi radio by default (NetworkManager ships it off)"
NM_STATE="${MNT}/var/lib/NetworkManager/NetworkManager.state"
mkdir -p "$(dirname "${NM_STATE}")"
if [ -f "${NM_STATE}" ]; then
    sed -i 's/^WirelessEnabled=false$/WirelessEnabled=true/' "${NM_STATE}"
else
    printf '[main]\nWirelessEnabled=true\n' > "${NM_STATE}"
fi
grep -qxF 'WirelessEnabled=true' "${NM_STATE}"
echo "NetworkManager WirelessEnabled set to true"

# --- enable ssh -------------------------------------------------------------
# openssh-server is installed and sshd_config is present, but ssh.service is
# NOT in multi-user.target.wants — confirmed by inspecting the built image
# directly. sshswitch.service (/usr/lib/raspberrypi-sys-mods/sshswitch) IS
# enabled and, on paper, does the right thing: if /boot/firmware/ssh exists it
# `systemctl enable --now ssh`s and deletes the marker. We ship that marker
# below. But real-hardware testing on Trixie found the Pi fully reachable
# (wifi fixed) with SSH still refusing connections outright — nothing
# listening on port 22 — despite the marker surviving to boot and the audit
# below passing clean. sshswitch's own ordering (After=boot-firmware.mount)
# looks correct in the unit file; the actual failure mode on real hardware
# was never root-caused past that.
#
# What settled it: flashing an *official* (non-custom) Trixie image through
# Raspberry Pi Imager's own "cloudinit-rpi" customisation path and inspecting
# what Imager itself writes. It does NOT create a /boot/ssh or
# /boot/firmware/ssh marker at all — sshswitch is never involved. Instead it
# puts a live command directly in user-data:
#   runcmd:
#     - [ systemctl, enable, --now, ssh ]
# Raspberry Pi's own tooling routes around sshswitch entirely on Trixie. We
# do the same: rewrite user-data's existing (harmless, always-commented-out)
# `#runcmd:` example block into a live one carrying that exact command. This
# runs regardless of whether the user (or Imager, which never touches our
# sideloaded image — see below) supplies any other customisation at all, so
# ssh reachability no longer depends on sshswitch, a marker file, or the user
# editing anything. The marker file is kept too, as a free second path; it
# just isn't trusted as the primary mechanism any more.
banner "Enabling SSH via the classic /boot/ssh marker file"
touch "${MNT}/boot/firmware/ssh"
[ -f "${MNT}/boot/firmware/ssh" ]
echo "/boot/firmware/ssh marker created (sshswitch.service will enable+start ssh on first boot, belt-and-suspenders)"

banner "Enabling SSH via a live cloud-init runcmd (the mechanism Imager itself uses)"
USER_DATA="${MNT}/boot/firmware/user-data"
[ -f "${USER_DATA}" ]
grep -qF '#runcmd:' "${USER_DATA}"
sed -i 's/^#runcmd:$/runcmd:\n- [ systemctl, enable, --now, ssh ]/' "${USER_DATA}"
grep -qxF -- '- [ systemctl, enable, --now, ssh ]' "${USER_DATA}"
echo "user-data now unconditionally enables+starts ssh on first boot via cloud-init runcmd"

# --- guarantee ssh.service can actually start: host keys ------------------
# The two fixes above only get ssh.service *asked* to start — on real
# hardware it still failed, with the journal showing the actual culprit:
#   Process: ExecStartPre=/usr/sbin/sshd -t (code=exited, status=1/FAILURE)
#   sshd: no hostkeys available -- exiting
# regenerate_ssh_host_keys.service (the raspberrypi-sys-mods unit that
# generates them — this image intentionally ships none, so every card gets
# its own) never ran: `systemctl status` showed
#   Condition: start condition unmet
#   ... skipped, unmet condition check
# Its ConditionFirstBoot=yes evaluated false on what genuinely was the first
# real boot — a known systemd race where systemd-machine-id-commit.service
# can consume the /run/systemd/first-boot marker before other
# ConditionFirstBoot=yes units get a turn. Confirmed on real hardware via
# console + journalctl, not guessed from static analysis.
#
# Rather than fight that race, stop depending on it. A drop-in on
# ssh.service itself generates any missing host keys as its own first
# ExecStartPre — self-sufficient regardless of what triggers ssh.service
# (sshswitch, our runcmd above, or a manual start later), and immune to the
# user hand-editing or deleting user-data entirely, since it lives in the
# rootfs, not the boot partition. `ExecStartPre=` with no value first clears
# the inherited `sshd -t` entry so we can re-add it *after* our own step —
# a plain drop-in only appends, which would run keygen after the config
# test that's actually failing.
mkdir -p "${MNT}/etc/systemd/system/ssh.service.d"
cat > "${MNT}/etc/systemd/system/ssh.service.d/inkypi-hostkeys.conf" <<'DROPIN'
[Service]
ExecStartPre=
ExecStartPre=/usr/bin/ssh-keygen -A
ExecStartPre=/usr/sbin/sshd -t
DROPIN
echo "ssh.service now generates its own host keys before starting, independent of regenerate_ssh_host_keys.service"

# --- first-boot instructions --------------------------------------------------
banner "Writing first-boot instructions"
# Pi OS Trixie dropped the old custom.toml/raspberrypi-sys-mods firstboot
# mechanism entirely (no more init=.../firstboot in cmdline.txt, no more
# init_config or python3-toml in the rootfs). First-boot customisation is now
# cloud-init: the boot partition already ships stock user-data/network-config
# templates, and Pi Imager's "Edit Settings" writes into those same files
# rather than a custom.toml it used to create from scratch.
cat > "${MNT}/boot/firmware/inkypi-readme.txt" <<'NOTE'
InkyPi pre-installed image (JTN-533)
====================================

This image already has InkyPi installed and enabled, and SSH is already
on (no marker file, no setup needed — it just works). It is NOT joined
to any network and has NO login account until you set those up by hand.

IMPORTANT: Raspberry Pi Imager's "Edit Settings" (gear icon) does NOT
appear for this image. That dialog only exists for the official OS
images Imager downloads itself — a sideloaded/custom .img.xz like this
one gets none of it, on any version of Imager. Flashing this image
writes it byte-for-byte with zero customisation; there is nothing to
configure at flash time.

Instead, before powering the Pi on for the first time, mount this same
boot partition on your computer (Windows/Mac/Linux all read FAT32
natively — no tools needed) and hand-edit two plain-text files already
sitting here:

    user-data       — create your login account (see the commented-out
                      `#users:` example already in the file — uncomment
                      it, set `name:`/`passwd:` or `ssh_authorized_keys:`)
    network-config  — join Wi-Fi (see the commented-out `wifis:` example
                      — uncomment it, set your SSID and password)

Both are stock cloud-init NoCloud templates; everything in them is
commented out by default (deliberately inert, so nothing half-applies).
Uncomment only what you need — format details are in each file's own
comments, or https://cloudinit.readthedocs.io/.

Wi-Fi radio note: this image enables the radio itself by default
(stock Pi OS ships NetworkManager with it off until a regulatory
domain / country is set, which a headless device has no way to prompt
for). Once you've set an SSID/password in network-config, if it still
won't join: (1) double-check the SSID/password; (2) set a country —
add `regulatory-domain: "US"` (your ISO code) under the wifi
interface block in network-config, indented to match `dhcp4:`; (3) as
a last resort, append this to the end of cmdline.txt on this partition
(same line, space-separated, no newline):
    cfg80211.ieee80211_regdom=US

Once the Pi joins your network, visit:
    http://<hostname>.local/
in a browser on the same LAN — the InkyPi web UI will be up. SSH in as
whatever account you created in user-data.
NOTE

# --- remove everything the build added ----------------------------------------
remove_scaffolding() {
    banner "Removing build scaffolding"
    # The stubs are the serious one. /usr/local/sbin comes BEFORE /usr/sbin in
    # root's PATH, so left behind they shadow the real binaries forever:
    #   * raspi-config becomes a permanent no-op. On Bookworm this broke the
    #     wifi regulatory domain specifically (raspi-config nonint
    #     do_wifi_country, called from the old custom.toml firstboot flow).
    #     Trixie's cloud-init sets the regulatory domain itself via
    #     network-config instead, but raspi-config still needs to be the real
    #     binary for whatever else on first boot expects it on PATH.
    #   * systemctl silently no-ops start/stop/restart/is-active, so anything
    #     asking systemd to act at runtime succeeds without acting.
    rm -f "${MNT}/usr/local/sbin/raspi-config" "${MNT}/usr/local/sbin/systemctl"

    # Restore the image's own resolv.conf. The builder's points at 127.0.0.53,
    # systemd-resolved's stub listener, which Pi OS Lite does not run — so DNS
    # failed on every flashed device.
    if [ -e "${MNT}/etc/resolv.conf.build-orig" ]; then
        mv "${MNT}/etc/resolv.conf.build-orig" "${MNT}/etc/resolv.conf"
    fi

    # NOT removed: /opt/inkypi-src. It looks like build residue and is not.
    # install.sh symlinks the app into the checkout rather than copying it —
    #     ln -sf "$SRC_PATH" "$INSTALL_STAGING/src"      (install/install.sh)
    # so /usr/local/inkypi/src points at /opt/inkypi-src/src. Deleting the
    # clone leaves a dangling symlink and the service dies on every boot with
    #     realpath: /usr/local/inkypi/src/inkypi.py: No such file or directory
    # Its .git is load-bearing too: do_update.sh and rollback.sh run git
    # against that checkout, so stripping the history breaks in-place updates.

    # Blank machine-id so each flashed card generates its own. dpkg populates
    # it during the chroot run, and a shared id means colliding DHCP leases
    # once more than one device is on a network. Empty is what pi-gen ships.
    truncate -s 0 "${MNT}/etc/machine-id"
    rm -f "${MNT}/var/lib/dbus/machine-id"
}
remove_scaffolding

# --- footprint ----------------------------------------------------------------
banner "Cleaning caches and logs"
chroot "${MNT}" /bin/bash -euxo pipefail -c '
  apt-get clean
  rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*.deb
  rm -rf /root/.cache/pip /root/.cache/uv
  rm -rf /tmp/* /var/tmp/*
  find /var/log -type f -exec truncate -s 0 {} +
'
# Last chroot is done, so the x86-side emulator can come out.
rm -f "${MNT}/usr/bin/qemu-aarch64-static"

if [ "${FAST}" -eq 0 ]; then
    dd if=/dev/zero of="${MNT}/ZEROFILL" bs=1M status=progress || true
    rm -f "${MNT}/ZEROFILL"
fi

cleanup
trap - EXIT
LOOP=""

# --- shrink -------------------------------------------------------------------
banner "Shrinking with pishrink ${PISHRINK_TAG}"
curl -fsSL -o pishrink.sh \
    "https://raw.githubusercontent.com/Drewsif/PiShrink/refs/tags/${PISHRINK_TAG}/pishrink.sh"
echo "${PISHRINK_SHA256}  pishrink.sh" > pishrink.sha256
sha256sum -c pishrink.sha256
chmod +x pishrink.sh
./pishrink.sh -s "${BASE_IMG}"

# --- verify the shrink didn't corrupt the filesystem ------------------------
# pishrink runs its own fsck+resize2fs internally and reported clean here, but
# a real build was found to still come out of that step with dangling extents
# on the rootfs (inodes pointing at physical blocks beyond the new, smaller
# filesystem size) — e2fsprogs 1.47.0's resize2fs shrink interacting badly
# with the orphan_file feature, non-deterministically: an earlier build of
# the exact same pipeline came out clean, this one didn't. The corruption is
# invisible to a build log (every step reports success) and to a casual
# `mount` (the kernel driver tolerates it enough to serve most files) — it
# only surfaces under a strict reader like debugfs or e2fsck, which is
# exactly what ships to users. Confirmed fixable with e2fsck -fy; make that
# fix mandatory rather than trusting pishrink's internal check.
banner "Verifying rootfs integrity after shrink"
# fdisk right-aligns the Start column, so rows can begin with spaces — match
# on the field being numeric rather than on the line starting with a digit
# (same approach audit_pi_image.sh uses).
read -r _BOOT_START ROOT_START <<<"$(
    fdisk -l -o Start,Type "${BASE_IMG}" 2>/dev/null \
        | awk '$1 ~ /^[0-9]+$/ {printf "%d ", $1}'
)"
ROOT_PART_OFF=$(( ROOT_START * 512 ))
FSCK_LOOP=$(losetup --show -f -o "${ROOT_PART_OFF}" "${BASE_IMG}")
set +e
e2fsck -fy "${FSCK_LOOP}"
FSCK_STATUS=$?
set -e
if [ "${FSCK_STATUS}" -ge 4 ]; then
    losetup -d "${FSCK_LOOP}"
    echo "ERROR: e2fsck could not fully repair the rootfs after shrink (exit ${FSCK_STATUS})" >&2
    exit 1
fi
# A pass that had to fix anything (exit 1/2) can still leave stale metadata
# a strict reader flags; run again and require a genuinely clean exit 0.
if [ "${FSCK_STATUS}" -ne 0 ]; then
    e2fsck -fy "${FSCK_LOOP}"
fi
losetup -d "${FSCK_LOOP}"
echo "rootfs integrity confirmed clean after shrink"

# --- package ------------------------------------------------------------------
banner "Packaging"
IMG_NAME="inkypi-${VERSION}-pi-zero-2-w.img"
mv "${BASE_IMG}" "${IMG_NAME}"
if [ "${FAST}" -eq 1 ]; then
    xz -0 -T 0 -v "${IMG_NAME}"
else
    xz -9 -T 0 -v "${IMG_NAME}"
fi
sha256sum "${IMG_NAME}.xz" > "${IMG_NAME}.xz.sha256"
ls -la "${IMG_NAME}.xz" "${IMG_NAME}.xz.sha256"

# Hand the packaging results to the workflow when running under Actions; the
# verify-boot and attach-release jobs key off these.
if [ -n "${GITHUB_OUTPUT:-}" ]; then
    {
        echo "image_name=${IMG_NAME}.xz"
        echo "image_sha256=$(awk '{print $1}' "${IMG_NAME}.xz.sha256")"
        echo "image_size=$(stat -c %s "${IMG_NAME}.xz")"
        echo "version=${VERSION}"
        echo "tag=${TAG}"
    } >> "${GITHUB_OUTPUT}"
fi

echo ""
echo "Built ${BUILD_DIR}/${IMG_NAME}.xz"
echo "Audit it with:  ./scripts/audit_pi_image.sh ${BUILD_DIR}/${IMG_NAME}.xz"
