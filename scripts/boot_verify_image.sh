#!/usr/bin/env bash
# boot_verify_image.sh — boot a Pi OS image under qemu and assert it reaches a
# login prompt.
#
# Used by the `verify-boot` job in .github/workflows/build-pi-image.yml
# (JTN-533) and runnable by hand, which is the point: the boot arguments are
# fiddly enough that a 25-minute CI round trip is a bad way to iterate on them.
#
#   ./scripts/boot_verify_image.sh path/to/inkypi-1.0.2-pi-zero-2-w.img.xz
#   ./scripts/boot_verify_image.sh --help
#
# Accepts a .img or .img.xz. Needs qemu-system-arm, xz-utils, and sudo for the
# loop-mount used to read the boot partition.
#
# How it boots, and why:
#
#   qemu's raspi machines do not run the Raspberry Pi firmware, so nothing
#   reads config.txt/cmdline.txt off the boot partition — the kernel, DTB and
#   command line have to be handed to qemu directly. We pull all three out of
#   the image so the test exercises the shipped kernel and the shipped root=
#   rather than substitutes.
#
#   -M raspi3b, because the Pi Zero 2 W is a BCM2710 — the same core. A generic
#   `virt` machine would need a foreign distro kernel plus an initramfs (distro
#   arm64 kernels build virtio_blk as a module, so with no initrd the rootfs
#   never mounts) and would prove nothing about kernel8.img.
#
#   Both UARTs are captured. qemu wires serial_hd(0) to the PL011 (ttyAMA0) and
#   serial_hd(1) to the mini UART (ttyS0); on a Pi 3 the PL011 is dedicated to
#   Bluetooth and the DTB points the console at the mini UART. Attaching only
#   one of them yields a completely silent boot.
set -euo pipefail

# Emulation without KVM runs roughly 2x slower than real time — a measured run
# reached kernel t=13s inside 30s of wall clock. A full Pi OS Lite boot is well
# under two minutes here; the rest of the budget is margin for a loaded runner.
TIMEOUT="${BOOT_VERIFY_TIMEOUT:-600}"
WORKDIR="${BOOT_VERIFY_WORKDIR:-.boot-verify}"
KEEP_RUNNING=0

usage() {
    cat <<'USAGE'
Usage: boot_verify_image.sh [options] <image.img|image.img.xz>

Boots the image under qemu-system-aarch64 (-M raspi3b) and waits for a
login prompt on either UART.

Options:
  -t, --timeout SECONDS   Boot budget (default 600, or $BOOT_VERIFY_TIMEOUT)
  -w, --workdir DIR       Scratch directory (default .boot-verify)
  -k, --keep              Leave qemu running on success for manual poking
  -h, --help              This message

Exit status is 0 if a login prompt appeared, 1 otherwise. On failure both
UART logs are printed.

Environment:
  GITHUB_OUTPUT   If set, "verified=true|false" is appended to it.
USAGE
}

IMAGE=""
while [ $# -gt 0 ]; do
    case "$1" in
        -t|--timeout) TIMEOUT="$2"; shift 2 ;;
        -w|--workdir) WORKDIR="$2"; shift 2 ;;
        -k|--keep)    KEEP_RUNNING=1; shift ;;
        -h|--help)    usage; exit 0 ;;
        -*)           echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
        *)            IMAGE="$1"; shift ;;
    esac
done

if [ -z "${IMAGE}" ]; then
    echo "ERROR: no image given" >&2
    usage >&2
    exit 2
fi
if [ ! -f "${IMAGE}" ]; then
    echo "ERROR: no such file: ${IMAGE}" >&2
    exit 2
fi

for tool in qemu-system-aarch64 xz losetup truncate; do
    if ! command -v "${tool}" >/dev/null 2>&1; then
        echo "ERROR: ${tool} not found." >&2
        echo "  Debian/Ubuntu: sudo apt-get install -y qemu-system-arm xz-utils" >&2
        exit 2
    fi
done

IMAGE=$(readlink -f "${IMAGE}")
mkdir -p "${WORKDIR}"
cd "${WORKDIR}"

banner() {
    echo ""
    echo "======================================================================"
    echo "  $1"
    echo "======================================================================"
}

# ── decompress ────────────────────────────────────────────────────────────────
banner "Preparing image"
case "${IMAGE}" in
    *.xz)
        IMG="$(basename "${IMAGE%.xz}")"
        if [ ! -f "${IMG}" ]; then
            echo "Decompressing $(basename "${IMAGE}") ..."
            xz -dc -T 0 "${IMAGE}" > "${IMG}"
        else
            echo "Reusing already-decompressed ${IMG}"
        fi
        ;;
    *)
        IMG="$(basename "${IMAGE}")"
        [ -f "${IMG}" ] || cp --sparse=always "${IMAGE}" "${IMG}"
        ;;
esac

# ── extract kernel, dtb, cmdline from the boot partition ──────────────────────
LOOP=$(sudo losetup --show -Pf "${IMG}")
# shellcheck disable=SC2317 # only invoked indirectly via `trap ... EXIT` below
cleanup_loop() {
    sudo umount ./mnt-boot 2>/dev/null || true
    sudo losetup -d "${LOOP}" 2>/dev/null || true
}
trap cleanup_loop EXIT
mkdir -p ./mnt-boot
sudo mount "${LOOP}p1" ./mnt-boot
# Pi OS Lite arm64 boots kernel8.img; bcm2710-rpi-3-b.dtb is the DTB matching
# the machine qemu emulates.
sudo cp ./mnt-boot/kernel8.img ./kernel8.img
sudo cp ./mnt-boot/bcm2710-rpi-3-b.dtb ./boot.dtb
sudo cp ./mnt-boot/cmdline.txt ./cmdline.txt
sudo chown "$(id -u):$(id -g)" kernel8.img boot.dtb cmdline.txt
sudo umount ./mnt-boot
sudo losetup -d "${LOOP}"
trap - EXIT

echo "Shipped cmdline.txt:"
cat cmdline.txt

# Rewrite only the console arguments; root= and everything else are kept
# verbatim so a broken root= or fstab still fails the test.
#
# Every console= has to go, not just console=serial0. serial0 is a Pi firmware
# alias the kernel does not understand (the firmware resolves it before boot,
# and qemu runs no firmware). And the kernel gives /dev/console to the LAST
# console=, so leaving Pi OS's trailing console=tty1 in place would put getty
# on the virtual terminal, where no serial log can see it.
#
# `quiet` goes too — on failure the kernel log is the diagnostic. So does the
# firstboot init=: it reboots partway through to resize the rootfs, which a log
# scraper cannot tell apart from a hang.
CMDLINE=$(tr -d '\n' < cmdline.txt \
    | sed -E 's/console=[^ ]*//g
              s#init=/usr/lib/raspberrypi-sys-mods/firstboot##g
              s/(^| )quiet( |$)/ /g
              s/(^| )resize( |$)/ /g
              s/  +/ /g
              s/^ //; s/ $//')
# earlycon writes straight to the PL011 MMIO window before any device probing,
# so a silent boot can be told apart from a console that never bound.
CMDLINE="${CMDLINE} earlycon=pl011,0x3f201000"
# Name every candidate console. The kernel silently ignores a console= naming
# a device that does not exist, registers the ones that do, and gives
# /dev/console to the last one it registered; systemd-getty-generator then
# spawns a getty on each registered console. So listing all three is safe and
# order only decides which gets /dev/console.
#
# ttyAMA1 goes last because it is the one that actually shows up: Pi OS's DTB
# aliases serial1 = &uart0, so the PL011 at 0x3f201000 enumerates as ttyAMA1,
# not ttyAMA0. And the mini UART never probes under qemu at all
# ("bcm2835-aux-uart ...: unable to register 8250 port"), so ttyS0 does not
# exist either. Naming only ttyAMA0/ttyS0 bound no console at all, which the
# kernel reported as "unable to open an initial console" — no getty, no login
# prompt, and a log that only ever contained earlycon output.
CMDLINE="${CMDLINE} console=ttyS0,115200 console=ttyAMA0,115200"
CMDLINE="${CMDLINE} console=ttyAMA1,115200"
# keep_bootcon stops the kernel unregistering earlycon once a real console
# appears, and ignore_loglevel stops systemd-sysctl silencing us when it applies
# Pi OS's kernel.printk. Without the pair the log died mid-boot at
# "Starting systemd-sysctl.service" and never resumed, which reads exactly like
# a hang: the guest was still running, we had simply gone blind. Everything we
# can see arrives over printk, because /dev/console never opens under qemu
# ("unable to open an initial console") and systemd falls back to /dev/kmsg.
CMDLINE="${CMDLINE} keep_bootcon ignore_loglevel"
# Pin systemd's own logging to kmsg for the whole boot. By default systemd
# switches from kmsg to the journal the moment journald starts, and since the
# journal is a file we never see, its messages vanished at
# "Started systemd-journald.service" — leaving only kernel output, which stops
# entirely once the system goes quiet. That looked like a hang at t=32s when
# the boot was almost certainly still progressing, and it means
# "Reached target multi-user.target" could never appear.
CMDLINE="${CMDLINE} systemd.log_target=kmsg systemd.show_status=true"
# Forward the journal to kmsg as well, so output from services themselves
# reaches us. Units ship StandardError=journal, so when one fails all we would
# otherwise see is systemd's "Failed to start ..." with no reason attached —
# which is exactly what happened to inkypi.service. printk.devkmsg=on lifts the
# kmsg rate limit that would otherwise drop messages under that extra volume,
# including possibly the boot-completion line this script waits for.
CMDLINE="${CMDLINE} systemd.journald.forward_to_kmsg=1 printk.devkmsg=on"

# Mask the two units that cannot possibly succeed under emulation, so the gate
# measures the image rather than qemu's missing hardware.
#
# inkypi.service drives an Inky e-paper HAT. Its driver calls inky.auto(),
# which identifies the panel by reading an EEPROM over I2C — there is no HAT
# here, so it fails every time, and the unit is configured to keep trying:
# Restart=on-failure, RestartSec=60, StartLimitBurst=5. That loop ate ~350s of
# a 600s budget before tripping its start limit, and multi-user.target sat
# behind it. Whether the app runs on real hardware is not something a
# hardware-free boot can answer; scripts/audit_pi_image.sh checks its wiring
# instead (src symlink resolves, venv, launcher, unit enabled, i2c-dev).
#
# NetworkManager-wait-online holds network-online.target until it gives up,
# and qemu's raspi3b emulates no NIC at all. inkypi.service is ordered after
# network-online.target, so this delay stacks on top of the one above.
CMDLINE="${CMDLINE} systemd.mask=inkypi.service"
CMDLINE="${CMDLINE} systemd.mask=NetworkManager-wait-online.service"
echo "Boot cmdline: ${CMDLINE}"

# ── pad to a power of two ─────────────────────────────────────────────────────
# qemu's raspi machines emulate a real SD controller and reject any card whose
# size is not a power of two. pishrink deliberately leaves the image at its
# minimum size, so pad a copy. The source image is left untouched.
BYTES=$(stat -c %s "${IMG}")
SD_BYTES=1
while [ "${SD_BYTES}" -lt "${BYTES}" ]; do
    SD_BYTES=$((SD_BYTES * 2))
done
cp --sparse=always "${IMG}" sd.img
truncate -s "${SD_BYTES}" sd.img
echo "Padded $(numfmt --to=iec "${BYTES}") image to $(numfmt --to=iec "${SD_BYTES}") SD card"

# ── boot ──────────────────────────────────────────────────────────────────────
banner "Booting (budget ${TIMEOUT}s, no KVM — every instruction is emulated)"
: > uart-pl011.log
: > uart-mini.log
: > qemu-stderr.log

# Redirect rather than pipe: in a pipeline $! is the last element, so the kill
# below would hit the wrong process and leave qemu orphaned.
timeout "${TIMEOUT}" qemu-system-aarch64 \
    -M raspi3b \
    -m 1024 \
    -kernel kernel8.img \
    -dtb boot.dtb \
    -drive file=sd.img,format=raw,if=sd \
    -append "${CMDLINE}" \
    -serial file:uart-pl011.log \
    -serial file:uart-mini.log \
    -display none \
    -no-reboot \
    > qemu-stderr.log 2>&1 &
QPID=$!

dump_logs() {
    for f in uart-pl011.log uart-mini.log qemu-stderr.log; do
        echo "----- ${f} ($(wc -c < "${f}" 2>/dev/null || echo 0) bytes) -----"
        tail -200 "${f}" 2>/dev/null || true
    done
    echo "----------------------------------------"
}

record() {
    [ -n "${GITHUB_OUTPUT:-}" ] && echo "verified=$1" >> "${GITHUB_OUTPUT}"
    return 0
}

fail() {
    echo ""
    echo "FAIL: $1"
    dump_logs
    kill -9 "${QPID}" 2>/dev/null || true
    record false
    exit 1
}

# What counts as a successful boot.
#
# "login:" is the strongest signal — getty running means userspace is fully up —
# but it depends on a getty being attached to a UART we can see, and under qemu
# /dev/console never opens, so it may never appear however healthy the image is.
#
# Reaching multi-user.target proves the same thing the gate actually cares
# about: the rootfs mounted, fstab was sane, and systemd brought userspace up.
# Those messages arrive over printk, which survives the missing console. Accept
# whichever shows up first.
BOOT_OK_PATTERNS='login:|Reached target multi-user.target|Reached target Multi-User System|Startup finished in'

for i in $(seq 1 "${TIMEOUT}"); do
    # Either UART satisfies the gate — the question is whether the image boots,
    # not which serial port it lands on.
    if grep -qhE "${BOOT_OK_PATTERNS}" uart-pl011.log uart-mini.log 2>/dev/null; then
        echo ""
        echo "PASS: boot completed at ${i}s"
        grep -hE "${BOOT_OK_PATTERNS}" uart-pl011.log uart-mini.log 2>/dev/null \
            | tail -3 | sed 's/^/  matched: /'
        # Reaching multi-user.target says the system came up; it says nothing
        # about whether the units on it actually started. inkypi.service failed
        # on a run that this gate reported as verified, so call out anything
        # that failed rather than letting a green result bury it.
        if grep -qh "Failed to start" uart-pl011.log uart-mini.log 2>/dev/null; then
            echo ""
            echo "WARNING: units failed during a boot that otherwise succeeded:"
            grep -hoE "Failed to start .*" uart-pl011.log uart-mini.log \
                2>/dev/null | tr -d '\r' | sort -u | sed 's/^/  /'
        fi
        dump_logs
        record true
        if [ "${KEEP_RUNNING}" -eq 1 ]; then
            echo "qemu left running as pid ${QPID} (--keep); kill it when done."
        else
            kill -9 "${QPID}" 2>/dev/null || true
        fi
        exit 0
    fi
    # If qemu is gone we will never see a login prompt, so stop now rather than
    # burning the whole budget and reporting a misleading timeout. A startup
    # failure (bad romfile, bad machine type) dies in well under a second.
    #
    # Distinguish the two ways qemu can disappear: `timeout` reaping it at the
    # end of the budget is not the same event as qemu falling over on its own,
    # and reporting the latter wording for the former sends the next reader
    # looking for a crash that never happened.
    if ! kill -0 "${QPID}" 2>/dev/null; then
        if [ "${i}" -ge $((TIMEOUT - 5)) ]; then
            fail "budget of ${TIMEOUT}s exhausted — no boot-completion marker"
        fi
        fail "qemu died on its own after ${i}s — see qemu-stderr.log"
    fi
    # Show the last console line, not just byte counts: a stalled byte count
    # looks identical whether the guest is wedged or simply slow, whereas the
    # kernel timestamp on the last line shows how far the boot actually got.
    if [ $((i % 30)) -eq 0 ]; then
        last=$(tail -n 1 uart-pl011.log 2>/dev/null | tr -d '\r' | cut -c1-100)
        echo "  ${i}s — pl011=$(wc -c < uart-pl011.log)b mini=$(wc -c < uart-mini.log)b | ${last}"
    fi
    sleep 1
done

fail "timed out after ${TIMEOUT}s — no login: prompt"
