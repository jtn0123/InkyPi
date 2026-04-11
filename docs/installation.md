# InkyPi Detailed Installation

## Flashing Raspberry Pi OS 

1. Install the Raspberry Pi Imager from the [official download page](https://www.raspberrypi.com/software/)
2. Insert the target SD Card into your computer and launch the Raspberry Pi Imager software
    - Raspberry Pi Device: Choose your Pi model
    - Operating System: Select the recommended system
    - Storage: Select the target SD Card

<img src="./images/raspberry_pi_imager.png" alt="Raspberry Pi Imager" width="500"/>

3. Click Next and choose Edit Settings on the Use OS customization? screen
    - General:
        - Set hostname: enter your desired hostname
            -  This will be used to ssh into the device & access the InkyPi UI on your network.
        - Set username & password
            - Do not use the default username and password on a Raspberry PI as this poses a security risk
        - Configure wireless LAN to your network
            - The InkyPi web server will only be accessible to devices on this network
        - Set local settings to your Time zone
    - Service:
        - Enable SSH:
            - Use password authentication
    - Options: leave default values

<p float="left">
  <img src="./images/raspberry_pi_imager_general.png" width="250" />
  <img src="./images/raspberry_pi_imager_options.png" width="250" /> 
  <img src="./images/raspberry_pi_imager_services.png" width="250" />
</p>

4. Click Yes to apply OS customization options and confirm

## Pi Zero 2 W setup notes

The Pi Zero 2 W is the cheapest officially-supported InkyPi target board, but its 512 MB of RAM and slow SD card I/O mean a few things are worth knowing up front.

### OS choice

As of `2025-12-04`, the **default Pi OS image is now Trixie (Debian 13)**. InkyPi v0.28.1+ supports it natively — earlier versions had a regression where `zramswap` was silently skipped on Trixie, causing OOMs during pip install on a Pi Zero 2 W (see JTN-528).

If you're flashing a Bookworm image instead (e.g. for compatibility with an older e-ink driver), use the `Raspberry Pi OS (Legacy, 64-bit) Lite` option in Imager — that's the renamed Bookworm channel since the Trixie cutover.

### `arm_64bit=1` requirement

The 2025-12-04 Trixie image sets `arm_64bit=1` explicitly in `/boot/firmware/config.txt`. Older Bookworm images may not. If you're upgrading an existing Pi from Bullseye/Bookworm and using a 64-bit kernel, double-check this line is present — without it, the 64-bit `kernel8.img` won't boot on the Zero 2 W.

### First-boot install time

A fresh `install.sh` run on a Pi Zero 2 W takes **roughly 15 minutes** end-to-end. The bottleneck is `pip install` building wheels for `numpy`, `Pillow`, and `playwright` on a single Cortex-A53 core. Don't kill the install or assume it's hung — `htop` will show `pip` consuming one core. zramswap (auto-enabled by `install.sh` on Bullseye/Bookworm/Trixie) is critical here; without it the build OOMs.

### Pre-built wheelhouse (faster first boot — JTN-604)

As of the version that resolves [JTN-604](https://linear.app/jtn0123/issue/JTN-604), tagged releases ship a pre-built **wheelhouse** — a tarball of every Python dependency compiled in advance for `linux_armv7l` (Pi Zero 2 W, 32-bit Trixie) and `linux_aarch64` (Pi 4/5, 64-bit). `install.sh` detects your architecture from `uname -m`, fetches the matching `inkypi-wheels-<version>-<arch>.tar.gz` from the current release's GitHub assets, verifies its sha256, and hands the extracted wheelhouse to pip via `--find-links` + `--prefer-binary` so no on-device compilation runs.

**Expected impact on a Pi Zero 2 W:**

- First-boot install time drops from **~15 min to ~2–3 min**
- Peak RAM during install drops from **~400 MB to < 200 MB** (no native compilation)
- SD card wear drops because pip never writes intermediate build objects
- The `--require-hashes` lockfile still applies — every wheel is verified against the hashes in `install/requirements.txt` before install

**Graceful fallback.** If the wheelhouse is missing (dev branches, network failure, unsupported arch, checksum mismatch, etc.), `install.sh` logs a `falling back to source install` message and runs the normal online pip install — no manual intervention needed.

**Opt out.** Set `INKYPI_SKIP_WHEELHOUSE=1` before running `install.sh` to skip the fetch entirely. Useful if you want to verify wheel builds reproduce locally or if you're debugging a dependency pin:

```bash
sudo INKYPI_SKIP_WHEELHOUSE=1 ./install.sh
```

### Watching the install via cloud-init

If you're driving an unattended install via cloud-init (e.g. via a `runcmd:` block in `user-data`), redirect the install output so you can watch it after the Pi boots:

```yaml
runcmd:
- sudo -u <your-user> git clone --branch v0.28.1 --depth 1 https://github.com/jtn0123/InkyPi.git /home/<your-user>/InkyPi
- chown -R <your-user>:<your-user> /home/<your-user>/InkyPi
- bash -c 'cd /home/<your-user>/InkyPi/install && ./install.sh > /var/log/inkypi-install.log 2>&1 && touch /var/log/inkypi-install.done || touch /var/log/inkypi-install.failed'
```

Then SSH in and `tail -f /var/log/inkypi-install.log`. Check for `/var/log/inkypi-install.done` or `/var/log/inkypi-install.failed` to know when it's done.

### NTP clock sync on first boot

The Pi Zero 2 W has no RTC battery. On boot, the system clock starts at the last `fake-hwclock` value, which can be months out of date if the Pi has been off for a while. Running `pip install` or `apt-get` before NTP syncs can cause TLS certificate validation failures ("certificate is not yet valid") because the system clock predates the server's SSL cert `notBefore` date.

As of the version that resolves [JTN-592](https://linear.app/jtn0123/issue/JTN-592), `install.sh` now waits up to 60 seconds for `systemd-timesyncd` to confirm NTP sync via `timedatectl show -p NTPSynchronized` before starting any package installs. If your Pi is connected to a network with NTP access, the clock typically syncs within 5–10 seconds of boot. If the clock does not sync within 60 seconds (e.g. on an offline network), install will proceed with a warning — TLS errors may still occur in that case, and you can set the clock manually with `sudo date -u -s 'YYYY-MM-DD HH:MM:SS'`.

### Pi Zero W vs Pi Zero 2 W

The "[Known Issues during Pi Zero W Installation](./troubleshooting.md#known-issues-during-pi-zero-w-installation)" section in the troubleshooting guide refers to the **original** 32-bit Pi Zero W, not the Pi Zero 2 W. The Zero 2 W is much more capable (4× Cortex-A53, ARMv8) and doesn't hit the same pip install issues — provided zramswap is enabled, which is automatic on InkyPi v0.28.1+.

## Re-editing user-data after first boot (cloud-init runcmd one-shot trap)

> **Observed on a real Pi Zero 2 W on 2026-04-10 (JTN-591).** This section exists because it's a completely silent failure that is very hard to diagnose on your own.

### What the trap looks like

You flash an SD card with Pi Imager, boot the Pi (maybe Wi-Fi fails, or you just want to add InkyPi later), re-mount the card on your computer, add a `runcmd:` block to `/boot/firmware/user-data`, insert the card, and boot again. The Pi joins the network fine — but `runcmd` never ran. The cloned repo is missing. No `inkypi.service`. No install logs.

### Why it happens

cloud-init's `runcmd` is a **per-instance one-shot module**. On first boot, cloud-init records a unique instance ID (typically something like `rpi-imager-1772926083770`) in:

```
/var/lib/cloud/data/instance-id
```

On every subsequent boot of that same SD card, cloud-init compares the current instance ID against the recorded one. They match, so cloud-init considers this boot "already done" and **skips all per-instance modules — including `runcmd` — completely silently**. It will not log an error. It will not warn you. The rendered `runcmd` shell script at `/var/lib/cloud/instances/<id>/scripts/runcmd` is simply the one baked during first boot (which was empty if you hadn't added `runcmd:` yet).

**This trap fires whenever:**
1. You flash an SD card and boot the Pi at least once (even a failed Wi-Fi boot counts).
2. You re-mount the SD card on your computer and add or change the `runcmd:` block in `user-data`.
3. You boot the Pi again.

### How to detect it

SSH into the Pi and check these signals:

```bash
# Is the instance-id file present? (It will be if the Pi booted at least once.)
cat /var/lib/cloud/data/instance-id

# Is the rendered runcmd script empty or missing the InkyPi commands?
cat /var/lib/cloud/instances/$(cat /var/lib/cloud/data/instance-id)/scripts/runcmd

# Check cloud-init logs — you will NOT see any runcmd output if it was skipped.
sudo journalctl -u cloud-init -n 100
sudo cat /var/log/cloud-init-output.log
```

If `runcmd` lines are absent from the logs and the rendered script is empty, you've hit the trap.

### How to recover — Option A (recommended)

On the Pi (via SSH), reset cloud-init state and reboot:

```bash
sudo cloud-init clean --logs
sudo reboot
```

After reboot, cloud-init will treat this as a fresh instance, regenerate the rendered `runcmd` script from the current `user-data`, and execute it. The InkyPi install will proceed normally.

A convenience wrapper script is provided at `scripts/cloud_init_clean.sh` — you can copy it to the Pi and run it there.

### How to recover — Option B (without SSH)

If you cannot SSH into the Pi, you can reset the instance ID from your computer while the SD card is mounted:

```bash
# On your Mac/Linux machine, with the SD card mounted (adjust the mount path):
sudo rm -rf /Volumes/bootfs/../rootfs/var/lib/cloud/instances/
sudo rm -f  /Volumes/bootfs/../rootfs/var/lib/cloud/data/instance-id
```

On your next boot, cloud-init will create a new instance record and run `runcmd` from scratch.

### How to recover — Option C (edit instance-id)

Alternatively, you can force a new instance ID by editing the file before reboot:

```bash
# On the Pi via SSH:
echo "fresh-instance-$(date +%s)" | sudo tee /var/lib/cloud/data/instance-id
sudo reboot
```

cloud-init will see a new instance ID and re-run all per-instance modules.

### Preventing the trap

If you know you'll need to iterate on `user-data` before the install is final, add the following at the **top** of your `user-data` file so cloud-init always runs `runcmd` regardless of instance ID:

```yaml
#cloud-config
# Force cloud-init to re-run per-instance modules on every boot.
# Remove this line once the install is stable.
always_rerun_modules: [runcmd]
```

> **Warning:** `always_rerun_modules: [runcmd]` makes `runcmd` run on *every* boot. Remove it once your install is confirmed working, or the install script will re-run each time the Pi reboots.
