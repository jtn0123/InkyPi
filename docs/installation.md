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
