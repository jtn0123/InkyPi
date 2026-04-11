# InkyPi 

[![CI](https://github.com/jtn0123/InkyPi/actions/workflows/ci.yml/badge.svg)](https://github.com/jtn0123/InkyPi/actions/workflows/ci.yml)
[![Quality Gate](https://sonarcloud.io/api/project_badges/measure?project=jtn0123_InkyPi&metric=alert_status)](https://sonarcloud.io/summary/overall?id=jtn0123_InkyPi)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License: GPL v3](https://img.shields.io/badge/license-GPL%20v3-green)](./LICENSE)

<img src="./docs/images/inky_clock.jpg" />


## About InkyPi 
InkyPi is an open-source, customizable E-Ink display powered by a Raspberry Pi. Designed for simplicity and flexibility, it allows you to effortlessly display the content you care about, with a simple web interface that makes setup and configuration effortless.

**Features**:
- Natural paper-like aesthetic: crisp, minimalist visuals that are easy on the eyes, with no glare or backlight
- Web Interface allows you to update and configure the display from any device on your network
- Minimal distractions: no LEDs, noise, or notifications — just the content you care about
- Easy installation and configuration, perfect for beginners and makers alike
- Open source project allowing you to modify, customize, and create your own plugins
- Set up scheduled playlists to display different plugins at designated times

**Plugins**:

| Category | Plugin | Description |
|----------|--------|-------------|
| Display | Clock | Customizable clock faces |
| | Countdown | Countdown timer to a target date |
| | Year Progress | Visual progress bar for the current year |
| | Todo List | Display a to-do list |
| Images | Image Upload | Upload and display any image from your browser |
| | Image Album | Cycle through an album of images |
| | Image Folder | Display images from a local folder |
| | Image URL | Display an image from a URL |
| | Unsplash | Random curated photos from Unsplash |
| | APOD | NASA Astronomy Picture of the Day |
| | WPOTD | Wikipedia Picture of the Day |
| News & Media | Newspaper | Front pages of major newspapers from around the world |
| | Comic | Daily comics from popular syndicated strips |
| | RSS | Display items from any RSS feed |
| Information | Weather | Current conditions and multi-day forecasts |
| | Calendar | Google, Outlook, or Apple Calendar integration |
| | GitHub | Contribution graph, stars, and sponsor stats |
| AI | AI Image | Generate images from prompts using OpenAI |
| | AI Text | Generate dynamic text from prompts using OpenAI |
| Utility | Screenshot | Capture and display a screenshot of any URL |

For documentation on building custom plugins, see [Building InkyPi Plugins](./docs/building_plugins.md).

## What's New in This Fork

This fork is under active development with a focus on stability, security, and UX polish.

| Feature | This Fork | Upstream |
|---------|:---------:|:--------:|
| API Keys Management UI | :white_check_mark: | :x: |
| Server-Side Settings Validation | :white_check_mark: | :x: |
| SSRF & Path Traversal Protection | :white_check_mark: | :x: |
| Image History Page with Pagination | :white_check_mark: | :x: |
| HTTP Caching | :white_check_mark: | :x: |
| Playlist UX (smart defaults, edit refresh) | :white_check_mark: | :x: |
| Accessibility (ARIA, dialog semantics) | :white_check_mark: | :x: |
| Fetch Timeouts & Error Feedback | :white_check_mark: | :x: |
| 20 Built-in Plugins | :white_check_mark: | 14 |
| Multi-threaded Server | :white_check_mark: | :x: |
| Hourly Weather Display | :white_check_mark: | :white_check_mark: |
| Display Saturation Setting | :white_check_mark: | :white_check_mark: |
| Bi-color Display Support | :white_check_mark: | :white_check_mark: |

## Hardware 
- Raspberry Pi (4 | 3 | Zero 2 W)
    - Recommended to get 40 pin Pre Soldered Header
- MicroSD Card (min 8 GB) like [this one](https://amzn.to/3G3Tq9W)
- E-Ink Display:
    - Inky Impression by Pimoroni
        - **[13.3 Inch Display](https://collabs.shop/q2jmza)**
        - **[7.3 Inch Display](https://collabs.shop/q2jmza)**
        - **[5.7 Inch Display](https://collabs.shop/ns6m6m)**
        - **[4 Inch Display](https://collabs.shop/cpwtbh)**
    - Inky wHAT by Pimoroni
        - **[4.2 Inch Display](https://collabs.shop/jrzqmf)**
    - Waveshare e-Paper Displays
        - Spectra 6 (E6) Full Color **[4 inch](https://www.waveshare.com/4inch-e-paper-hat-plus-e.htm?&aff_id=111126)** **[7.3 inch](https://www.waveshare.com/7.3inch-e-paper-hat-e.htm?&aff_id=111126)** **[13.3 inch](https://www.waveshare.com/13.3inch-e-paper-hat-plus-e.htm?&aff_id=111126)**
        - Black and White **[7.5 inch](https://www.waveshare.com/7.5inch-e-paper-hat.htm?&aff_id=111126)** **[13.3 inch](https://www.waveshare.com/13.3inch-e-paper-hat-k.htm?&aff_id=111126)**
        - See [Waveshare E-Ink displays](https://www.waveshare.com/product/raspberry-pi/displays/e-paper.htm?&aff_id=111126) or visit their [Amazon store](https://amzn.to/3HPRTEZ) for additional models. Note that some models like the IT8951-based displays are not supported. See later section on [Waveshare E-Ink](#waveshare-display-support) compatibility for more information.
- Picture Frame or 3D Stand
    - See [community.md](./docs/community.md) for 3D models, custom builds, and other submissions from the community

**Disclosure:** The links above are affiliate links. I may earn a commission from qualifying purchases made through them, at no extra cost to you, which helps maintain and develop this project.

## Installation
To install InkyPi, follow these steps:

1. Clone the repository:
    ```bash
    git clone https://github.com/jtn0123/InkyPi.git
    ```
2. Navigate to the project directory:
    ```bash
    cd InkyPi
    ```
3. Run the installation script with sudo:
    ```bash
    sudo bash install/install.sh [-W <waveshare device model>]
    ``` 
     Option: 
    
    * -W \<waveshare device model\> - specify this parameter **ONLY** if installing for a Waveshare display.  After the -W option specify the Waveshare device model e.g. epd7in3f.

    e.g. for Inky displays use:
    ```bash
    sudo bash install/install.sh
    ```

    and for [Waveshare displays](#waveshare-display-support) use:
    ```bash
    sudo bash install/install.sh -W epd7in3f
    ```


After the installation is complete, the script will prompt you to reboot your Raspberry Pi. Once rebooted, the display will update to show the InkyPi splash screen.

Note: 
- The installation script requires sudo privileges to install and run the service. We recommend starting with a fresh installation of Raspberry Pi OS to avoid potential conflicts with existing software or configurations.
- The installation process will automatically enable the required SPI and I2C interfaces on your Raspberry Pi.

For more details, including instructions on how to image your microSD with Raspberry Pi OS, refer to [installation.md](./docs/installation.md). You can also checkout [this YouTube tutorial](https://youtu.be/L5PvQj1vfC4).

## Update
To update your InkyPi with the latest code changes, follow these steps:
1. Navigate to the project directory:
    ```bash
    cd InkyPi
    ```
2. Fetch the latest changes from the repository:
    ```bash
    git pull
    ```
3. Run the update script with sudo:
    ```bash
    sudo bash install/update.sh
    ```
This process ensures that any new updates, including code changes and additional dependencies, are properly applied without requiring a full reinstallation.

## Development

### Local install verification

To verify `install/install.sh` against the current branch without real Pi hardware,
use the provided simulator (requires Docker with multi-platform support):

```bash
./scripts/sim_install.sh trixie    # Debian Trixie (default)
./scripts/sim_install.sh bookworm  # Debian Bookworm
./scripts/sim_install.sh bullseye  # Debian Bullseye
```

This builds an arm64 container capped at 512 MB RAM (matching the Pi Zero 2 W)
and runs `install.sh` end-to-end against your local checkout.
Always confirm on real hardware before merging install path changes.

### Running the web UI locally

To run the web UI locally without e-ink hardware:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r install/requirements-dev.txt
.venv/bin/python src/inkypi.py --dev --web-only
```

The dev server starts on port 8080. See [CONTRIBUTING.md](./CONTRIBUTING.md) for the full dev workflow and [docs/development.md](./docs/development.md) for platform-specific setup.

## Testing

```bash
scripts/test.sh                                        # fast local test runner (sharded)
scripts/test.sh tests/unit/test_refresh_task_stress.py  # single file
scripts/preflash_validate.sh                            # hardware-free pre-flash gate
```

See [docs/testing.md](./docs/testing.md) for coverage, browser/accessibility suites, pre-flash hardening lanes, and CI details.

## Uninstall
To uninstall InkyPi, simply run the following command:

```bash
sudo bash install/uninstall.sh
```

## Waveshare Display Support

Waveshare offers a range of e-Paper displays, similar to the Inky screens from Pimoroni, but with slightly different requirements. While Inky displays auto-configure via the inky Python library, Waveshare displays require model-specific drivers from their [Python EPD library](https://github.com/waveshareteam/e-Paper/tree/master/RaspberryPi_JetsonNano/python/lib/waveshare_epd).

This project has been tested with several Waveshare models. **Displays based on the IT8951 controller are not supported**, and **screens smaller than 4 inches are not recommended** due to limited resolution.

If your display model has a corresponding driver in the link above, it’s likely to be compatible. When running the installation script, use the -W option to specify your display model (without the .py extension). The script will automatically fetch and install the correct driver.

## License

Distributed under the GPL 3.0 License, see [LICENSE](./LICENSE) for more information.

This project includes fonts and icons with separate licensing and attribution requirements. See [Attribution](./docs/attribution.md) for details.

## Documentation

- [Architecture](./docs/architecture.md) — High-level component map and request/refresh flow
- [Development Setup](./docs/development.md) — Local dev environment on macOS, Linux, or Windows
- [API Keys](./docs/api_keys.md) — Configuring API keys for plugins (OpenAI, Google, etc.)
- [Testing](./docs/testing.md) — Test suite, sharding, browser tests, and coverage
- [Building Plugins](./docs/building_plugins.md) — Guide for creating custom plugins (includes a hello-world walkthrough)
- [Troubleshooting](./docs/troubleshooting.md) — Common issues and fixes

## Issues

Check out the [troubleshooting guide](./docs/troubleshooting.md). If you're still having trouble, feel free to create an issue on the [GitHub Issues](https://github.com/jtn0123/InkyPi/issues) page.

If you're using a Pi Zero W, note that there are known issues during the installation process. See [Known Issues during Pi Zero W Installation](./docs/troubleshooting.md#known-issues-during-pi-zero-w-installation) section in the troubleshooting guide for additional details.

---

Forked from [fatihak/InkyPi](https://github.com/fatihak/InkyPi).
