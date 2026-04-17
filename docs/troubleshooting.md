# Troubleshooting

## InkyPi Service not running

Check the status of the service:
```bash
sudo systemctl status inkypi.service
```

If the service is running, this should output `Active: active (running)`:
```bash
● inkypi.service - InkyPi App
     Loaded: loaded (/etc/systemd/system/inkypi.service; enabled; preset: enabled)
     Active: active (running) since Sun 2024-12-22 20:48:53 GMT; 28s ago
   Main PID: 48333 (bash)
      Tasks: 6 (limit: 166)
        CPU: 6.333s
     CGroup: /system.slice/inkypi.service
             ├─48333 bash /usr/local/bin/inkypi -d
             └─48336 python -u /home/pi/inky/src/inkypi.py -d
```

If the service is not running, check the logs for any errors or issues.

If the journal shows `Install in progress — refusing to start` (JTN-607), an earlier `install.sh` run left the `/var/lib/inkypi/.install-in-progress` lockfile in place — rerun `install.sh` to let it complete and clear the lockfile, or manually remove it with `sudo rm /var/lib/inkypi/.install-in-progress` if you are certain no install is running.

## Debugging

View the latest logs for the InkyPi service:
```bash
journalctl -u inkypi -n 100
```

Tail the logs:
```bash
journalctl -u inkypi -f
```

## Log Rotation

On a long-running Pi (weeks or months of 24/7 uptime), the systemd journal can quietly grow large enough to fill an SD card. A few commands help you keep it in check.

**Check current journal disk usage:**
```bash
journalctl --disk-usage
```

**Set a persistent size cap** by adding these lines to `/etc/systemd/journald.conf`:
```ini
SystemMaxUse=50M
RuntimeMaxUse=50M
```
Then restart the journal daemon to apply:
```bash
sudo systemctl restart systemd-journald
```

**Vacuum old logs immediately** (one-off cleanup):
```bash
sudo journalctl --vacuum-size=50M
```

> **Note:** The in-memory log buffer used in dev mode (`--dev`) holds at most 1,000 entries and is never written to disk, so it has no impact on journal size.

The InkyPi install and update scripts automatically enable persistent journald storage and apply `50M` caps for both `SystemMaxUse` and `RuntimeMaxUse` when no explicit journald settings already exist.

## Intermittent Wi-Fi reachability / SSH drops

If the Pi appears online but drops SSH or misses pings intermittently, check whether Wi-Fi power saving is enabled on `wlan0`:

```bash
nmcli -g 802-11-wireless.powersave connection show "$(nmcli -g GENERAL.CONNECTION device show wlan0 | head -n 1)"
```

`2` means disabled, which is the recommended setting for an always-on Pi. InkyPi now hardens NetworkManager-based installs and updates by writing a NetworkManager config drop-in and disabling Wi-Fi powersave on the active `wlan0` profile when possible.

To inspect the current link and roaming state:

```bash
nmcli -f GENERAL.STATE,GENERAL.CONNECTION,IP4.ADDRESS dev show wlan0
cat /proc/net/wireless
journalctl -b | grep -Ei 'wlan0|brcmfmac|CTRL-EVENT|deauth|disassoc'
```

If you still see drops after power-save hardening, compare signal strength across nearby APs with the same SSID and consider pinning the Pi to the strongest BSSID.

## Restart the InkyPi Service

```bash
sudo systemctl restart inkypi.service
```


## Run InkyPi Manually

If the InkyPi service is not running, try manually running the startup script to diagnose. This should output the logs to the terminal and make it easier to troubleshoot any errors:

```bash
sudo /usr/local/bin/inkypi -d
```

## API Key not configured

Some plugins require API Keys to be configured in order to run. These need to be configured in a .env file at the root of the project. See [API Keys](api_keys.md) for details.

## Clock/Sunset/Sunrise Time is wrong

If the displayed time is incorrect, your timezone setting may not be configured. You can update this in the Settings page of the Web UI.

## Failed to retrieve weather data

```bash
Failed to retrieve weather data
ERROR - root - Failed to retrieve weather data: b'{"cod":401, "message": "Please note that using One Call 3.0 requires a separate subscription to the One Call by Call plan. Learn more here https://openweathermap.org/price. If you have a valid subscription to the One Call by Call plan, but still receive this error, then please see https://openweathermap.org/faq#error401 for more info."}'
```

InkyPi uses the One Call API 3.0 API which requires a subscription but is free for up to 1,000 requests a day. See [API Keys](api_keys.md) for instructions.

## No EEPROM detected

```bash
RuntimeError: No EEPROM detected! You must manually initialise your Inky board.
```

InkyPi uses the [inky python library](https://github.com/pimoroni/inky) from Pimoroni to detect and interface with Inky displays. However, the auto-detect functionality does not work on some boards, which requires manual setup (see [Manual Setup](https://github.com/pimoroni/inky?tab=readme-ov-file#manual-setup)).

Manually import and instantiate the correct Inky module in src/display_manager.py. For the 7.3 Inky Impression, modify the file as follows:
```
@@ -1,5 +1,5 @@
 import os
-from inky.auto import auto
+from inky.inky_ac073tc1a import Inky
 from utils.image_utils import resize_image, change_orientation
 from plugins.plugin_registry import get_plugin_instance

@@ -8,7 +8,7 @@ class DisplayManager:
     def __init__(self, device_config):
         """Manages the display and rendering of images."""
         self.device_config = device_config
-        self.inky_display = auto()
+        self.inky_display = Inky()
         self.inky_display.set_border(self.inky_display.BLACK)
```

Then restart the inkypi service:
```
sudo systemctl restart inkypi.service
```

## Waveshare e-Paper EPD Devices

### Missing modules

Ensure that the necessary modeules are available in the python environment. Waveshare requires:

- gpiozero
- lgpio
- RPi.GPIO

in addition to the libraries that are normally installed for Inky screens.

### Screen not updating

Verify SPI configuration using `ls /dev/sp*`.  There should be two entries for _spidev0.0_ and _spidev0.1_.  

If only the first is visible, check _/boot/firmware/config.txt_. The regular install of InkyPi adds `dtoverlay=spi0-0cs` to the this file.  If it is there, either delete it (for default behaviour) or specifically add `dtoverlay=spi0-2cs`.

### ERROR: Failed to download Waveshare driver

The installation script attempts to fetch the EPD driver library based on the -W argument provided. Please double-check that:
- You’ve entered the correct display model.
- The corresponding driver file exists in the [waveshare e-Paper github repository](https://github.com/waveshareteam/e-Paper/tree/master/RaspberryPi_JetsonNano/python/lib/waveshare_epd).

Note: Some displays, such as the epd4in0e, are not included in the main library path above. Instead, they may be located under the [E-paper_Separate_Program](https://github.com/waveshareteam/e-Paper/tree/master/E-paper_Separate_Program) path. If your model is there, look under:
```bash
/RaspberryPi_JetsonNano/python/lib/waveshare_epd/
```

In this case, you’ll need to manually copy both the epdXinX.py and epdconfig.py files into:
```bash
InkyPi/src/display/waveshare_epd/
```

For example, to copy the driver and epdconfig files for epd13in3E (Waveshare Spectra 6 (E6) Full Color 13.3 inch display):
```bash
cd InkyPi/src/display/waveshare_epd/
curl -L -O https://raw.githubusercontent.com/waveshareteam/e-Paper/refs/heads/master/E-paper_Separate_Program/13.3inch_e-Paper_E/RaspberryPi/python/lib/epd13in3E.py
curl -L -O https://raw.githubusercontent.com/waveshareteam/e-Paper/refs/heads/master/E-paper_Separate_Program/13.3inch_e-Paper_E/RaspberryPi/python/lib/epdconfig.py
```

Additionally, you'll need the DEV_config* files in the same directory for your system. If you don’t know which file applies to your hardware, you can download all available DEV config files.
For example, for the epd13in3E display & Pi Zero 2 W, pull the following file:
```bash
curl -L -O https://raw.githubusercontent.com/waveshareteam/e-Paper/refs/heads/master/E-paper_Separate_Program/13.3inch_e-Paper_E/RaspberryPi/python/lib/DEV_Config_64_b.so
```

Once the files are in place, rerun the installation script. The script will detect the driver locally and skip the download step.

## Today's Newspaper not found

Daily newspaper front pages are sourced from [Freedom Forum](https://frontpages.freedomforum.org/gallery). The list of available newspapers may change periodically. InkyPi maintains an up-to-date list of newspapers provided by Freedom Forum, but there may be times when the list becomes outdated.

If you encounter this error, please feel free to open an Issue, including the name of the newspaper you were trying to access, and we'll work to update the list.

Also consider supporting the important work of Freedom Forum, an organization dedicated to promoting and protecting free press and the First Amendment: https://www.freedomforum.org/take-action/

## Known Issues during Pi Zero W Installation

Due to limitations with the Pi Zero W, there are some known issues during the InkyPi installation process. For more details and community discussion, refer to this [GitHub Issue](https://github.com/fatihak/InkyPi/issues/5).

### Pip Installation Error

#### Error message
```bash
WARNING: Retrying (Retry(total=4, connect=None, read=None, redirect=None, status=None)) after connection broken by 'ProtocolError('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))':
```

#### Recommended solution
Manually install the required pip packages in the inkypi virtual environment:
```bash
source "/usr/local/inkypi/venv_inkypi/bin/activate"
pip install -r install/requirements.txt
deactivate
```
Restart the inkypi service to apply the changes:
```bash
sudo systemctl restart inkypi.service
```

### Numpy ImportError

#### Error message
```bash
ImportError: Error importing numpy: you should not try to import numpy from
its source directory; please exit the numpy source tree, and relaunch
your python interpreter from there.
```

#### Recommended solution
To resolve this issue, manually reinstall the Pillow library in the inkypi virtual environment:
```bash
sudo su
source "/usr/local/inkypi/venv_inkypi/bin/activate"
pip uninstall Pillow
pip install Pillow
deactivate
```

Restart the inkypi service to apply the changes:
```bash
sudo systemctl restart inkypi.service
```

## Plugin Development Troubleshooting

> See also: [Building InkyPi Plugins](building_plugins.md) for the full plugin authoring guide.

### API Key Validation Failures

**Symptom:** The plugin error toast reads something like `"OPEN_WEATHER_MAP_SECRET API key not configured"`, `"GITHUB_SECRET API key not configured"`, or `"GOOGLE_AI_SECRET API key not configured"`. The display either retains the previous image or shows blank.

**Likely cause:** The required secret is missing from the `.env` file at the project root, or the file itself does not exist. All API-backed plugins call `device_config.load_env_key("<KEY_NAME>")` and raise a `RuntimeError` when the result is falsy.

**How to verify:**
```bash
grep -E 'OPEN_WEATHER_MAP_SECRET|GITHUB_SECRET|GOOGLE_AI_SECRET|OPEN_AI_SECRET|NASA_SECRET' /usr/local/inkypi/.env
```

**Fix:** Add the missing key to `.env` (create the file if needed) and restart the service. See [API Keys](api_keys.md) for per-plugin key names and where to obtain them.

---

### Plugin Fetch Timeouts (Newspaper, Comic, RSS)

**Symptom:** The journal shows `requests.exceptions.ReadTimeout` or `requests.exceptions.ConnectionError`. The Newspaper plugin may raise `"Newspaper front cover not found."`, the Comic plugin `"Failed to retrieve latest comic."`, and the RSS plugin `"Failed to parse RSS feed: …"`.

**Likely cause:** The upstream source (Freedom Forum, GoComics, the RSS feed URL) is temporarily unreachable or slow. On a Pi Zero the default HTTP timeout (20 s) can be hit during high-load periods. DNS resolution failures also surface as `ConnectionError`.

**How to verify:**
```bash
journalctl -u inkypi -n 50 | grep -E 'Timeout|ConnectionError|Failed to'
```
Try the URL manually from the Pi: `curl -I <feed_url>`.

**Fix:** Retry after a few minutes. For persistent issues, check that the Pi has network access (`ping 8.8.8.8`) and that the source service is operational. Increase the HTTP timeout via `INKYPI_HTTP_TIMEOUT_DEFAULT_S` in `.env` if the feed is reliably slow.

---

### Image Dimension Mismatch (`OutputDimensionMismatch`)

**Symptom:** The journal contains a log line like:

```
plugin_lifecycle: dimension_mismatch | plugin_id=my_plugin instance=… expected=800x480 actual=480x800 — skipping display push
```

The display is not updated; the previous image is retained.

**Likely cause:** The plugin's `generate_image` method returned an image whose size does not match the device resolution stored in `device.json`. This is validated by `OutputDimensionMismatch` in `src/utils/output_validator.py`. A 90-degree transposition is auto-corrected, but any other size mismatch raises the exception.

**How to verify:**
```bash
journalctl -u inkypi -n 100 | grep dimension_mismatch
```

**Fix:** In your plugin call `self.get_oriented_dimensions(device_config)` to obtain the correct `(width, height)` for the current orientation, and use that tuple when creating the `PIL.Image` object or calling `render_image`.

---

### Memory Pressure on Pi Zero

**Symptom:** The service is killed silently (`Main process exited`) or the journal shows `MemoryError` / Python `Killed`. Chromium-based plugins (Weather, Calendar, AI Text) are most affected. The Pi Zero W has only 512 MB of RAM shared with the OS.

**Likely cause:** Launching a headless Chromium instance for `render_image` consumes ~150–200 MB. Under memory pressure the Linux OOM killer terminates either Chromium or the InkyPi process.

**How to verify:**
```bash
journalctl -u inkypi -n 50 | grep -E 'Killed|MemoryError|OOM'
free -m
```

**Fix:**
1. Enable zram swap if not already active: `sudo systemctl enable --now zramswap`.
2. Increase the plugin refresh interval to reduce how often Chromium is launched.
3. Limit simultaneous playlist plugins to avoid back-to-back Chromium launches.
4. Consider a Pi Zero 2 W (512 MB with a faster CPU) for Chromium-heavy plugin sets.

---

### Screenshot Plugin Failures (Chromium Not Found / Sandbox Error)

**Symptom:** The error toast or journal reads `"Failed to take screenshot, please check logs."`. The journal may contain `"No supported browser found. Install Chromium or Google Chrome."` or a non-zero Chromium exit code such as `status=127`.

**Likely cause:** The Screenshot, Weather, Calendar, and AI Text plugins all depend on a headless Chromium binary (via `src/utils/image_utils.py`). If Chromium is not installed, or if the binary is present but the `--no-sandbox` flag is blocked by the OS, `take_screenshot` returns `None`.

**How to verify:**
```bash
which chromium chromium-headless-shell google-chrome 2>/dev/null
journalctl -u inkypi -n 50 | grep -i 'screenshot\|chromium\|browser'
```

**Fix:**
```bash
sudo apt-get install -y chromium-browser
sudo systemctl restart inkypi.service
```
If Chromium is present but crashes, check that `/dev/shm` is writable: `ls -la /dev/shm`. On constrained systems the `--disable-dev-shm-usage` flag (already set by InkyPi) moves temp files to `/tmp`; ensure `/tmp` has at least 64 MB free.

---

### Jinja2 Template Render Errors

**Symptom:** Plugin settings page shows a Jinja2 `UndefinedError` such as `'dict object' has no attribute 'foo'`, or the rendered HTML is blank/garbled. In some cases a value that should appear as plain text is HTML-escaped (e.g., `&lt;b&gt;` instead of `<b>`).

**Likely cause:** Two common issues:
1. A template variable expected by `settings.html` or `render/` templates was not added to the dict returned by `generate_settings_template` (or `template_params` in `render_image`).
2. Autoescape is enabled for `.html` files (see `base_plugin.py`). Any string that contains HTML and is passed as a template variable will be escaped unless wrapped with `{{ value | safe }}`.

**How to verify:**
```bash
journalctl -u inkypi -n 50 | grep -i 'UndefinedError\|TemplateSyntaxError\|jinja'
```
Run the dev server and navigate to the plugin settings page to see the full traceback in the terminal.

**Fix:**
- For missing variables: add the key to `generate_settings_template` before calling `render_image` or returning the template dict.
- For escaped HTML: use `{{ value | safe }}` only when the value is trusted and intentionally contains markup.
- For syntax errors: run `python -c "from jinja2 import Environment; env = Environment(); env.parse(open('src/plugins/<id>/render/<file>.html').read())"` to validate the template offline.

---

## Colors look washed out or incorrect

Some color inaccuracies are expected due to the physical limitations of e-ink displays, especially on multi-color panels with a limited color palette and dithering.

InkyPi provides several image enhancement controls in the Settings page that can help improve how images appear on your display: Saturation, Contrast, Sharpness, Brightness. These adjustments are applied to images using the Pillow ImageEnhance module before they are displayed. You can experiment with these values to find what looks best for your specific panel and content.

For more details on how each setting behaves, see the [Pillow documentation](https://pillow.readthedocs.io/en/stable/reference/ImageEnhance.html).

### Inky Driver Saturation

For Inky displays from Pimoroni, there is an additional option for `Inky Driver Saturation` in the Settings page. This controls the saturation of the palette to which an image is dithered to in the Inky library. Try setting this to '0' which seems to improve the quality of images displayed.

See [this response](https://github.com/pimoroni/inky/issues/225#issuecomment-3213935144) from the Pimoroni team for more details.
