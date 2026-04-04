# InkyPi Development Quick Start

## Development Without Hardware

The `--dev` flag enables complete development without requiring:

- Raspberry Pi hardware
- Physical e-ink displays (Inky pHAT/wHAT or Waveshare)
- Root privileges or GPIO access
- Linux-specific features (systemd)

Works on **macOS**, **Linux**, and **Windows** - no hardware needed!

## Setup
<table>
<tr>
<td>
Traditional setup method

```bash
# 1. Clone and setup
git clone https://github.com/fatihak/InkyPi.git
cd InkyPi

# 2. Quick start (recommended)
./scripts/dev.sh

# Or manual setup
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. Install Python dependencies and vendor assets
pip install -r install/requirements-dev.txt
bash install/update_vendors.sh
python src/inkypi.py --dev
```

</td>
<td>
Alternative method using devbox - works on macOS / any Linux distro / WSL2

```bash
setopt INTERACTIVE_COMMENTS # enable interactive comments in zsh

# 1. Install devbox and direnv (direnv is optional but recommended)
command -v devbox >/dev/null || curl -fsSL https://get.jetify.com/devbox | bash
command -v direnv >/dev/null || nix profile install "nixpkgs#direnv" \
  && eval "$(direnv hook ${SHELL##*/})" >> ~/.${SHELL##*/}rc \
  && source ~/.${SHELL##*/}rc # If not already present: install direnv, add hooks to shell rc and activate

# 2. Clone and setup
git clone https://github.com/fatihak/InkyPi.git
cd InkyPi # direnv reads .envrc -> runs devbox shell -> installs deps & activates venv

# 3. Run InkyPi in developer mode via devbox
devbox run dev # alternatively run `devbox shell` and then run `python src/inkypi.py --dev`
```

</td>
</tr>
</table>

**That's it!** Open http://localhost:8080 and start developing.

## What You Can Do

- **Develop plugins** - Create new plugins without hardware (no Raspberry Pi, nor physical displays)
- **Test UI changes** - Instant feedback on web interface modifications
- **Debug issues** - Full error messages in terminal
- **Verify rendering** - Check output in `runtime/mock_display_output/latest.png`
- **Cross-platform development** - Works on macOS, Linux, Windows

## Essential Commands

<table>
<tr>
<td>

Traditional activation method

```bash
source venv/bin/activate             # Activate virtual environment
python src/inkypi.py --dev           # Start development server (full program)
python src/inkypi.py --dev --web-only# Start web UI only (no background thread)
python src/inkypi.py --dev --fast-dev# Fast cycle, skip startup image
./scripts/web_only.sh                # Scripted web-only startup
deactivate                           # Exit virtual environment
```

</td>
<td>
devbox / direnv method

```bash
devbox run dev # run InkyPi in dev mode, terminating deactivates `devbox shell`

# direnv will activate / deactivate `devbox shell` automatically when entering
# and leaving the project directory (provided `direnv allow` has run once)... 
# Otherwise to manually activate / deactivate:
devbox shell                         # Installs deps, and activates Python virtual environment
python src/inkypi.py --dev           # Start development server
exit                                 # Exit devbox shell and deactivates Python virtual environment
```

</td>
</tr>
</table>

## Development Tips

1. **Check rendered output**: Images are saved to `runtime/mock_display_output/`
2. **Plugin development**: Copy an existing plugin as template (e.g., `clock/`)
3. **Configuration**: Edit `src/config/device_dev.json` for display settings
4. **Hot reload**: You can run via Flask dev server for code reload. When `INKYPI_ENV=dev` or running with `--dev`, plugin modules are reloaded on access so you can iterate without restarting.

```bash
export FLASK_APP=src.inkypi:create_app
export INKYPI_ENV=dev
flask --debug run -p 8080
```

## Development Tools

- Plugin validator

```bash
python scripts/plugin_validator.py         # validate all plugins
python scripts/plugin_validator.py clock   # validate a single plugin
```

- JSON Schemas (for IDE/CI)
  - `src/config/schemas/device_config.schema.json`
  - `src/config/schemas/plugin-info.schema.json`

## Testing Your Changes

1. Configure a plugin through the web UI
2. Click "Display" button
3. Check `runtime/mock_display_output/latest.png` for result
4. Iterate quickly without deployment
5. BasePlugin notes:
   - Jinja environment is initialized even if a plugin lacks its own `render/` directory. Base templates under `plugins/base_plugin/render/` are always available.
   - If a plugin does not provide `settings.html`, the UI will include `base_plugin/settings.html` by default.

## Other Requirements

InkyPi relies on system packages for some features, which are normally installed via the `install.sh` script. **(Skip if using devbox method)**

### Linux

**(Skip this section if using devbox method)**

The required packages can be found in this file:

https://github.com/fatihak/InkyPi/blob/main/install/debian-requirements.txt

Use your favourite package manager (such as `apt`) to install them.

### Chromium or Google Chrome browser

InkyPi uses `--headless` mode to render HTML templates to PNGs using a Chrome-like browser.

Different platforms have different available browser packages; refer to the table below:

| Platform | Recommended Package | Notes |
| --- | --- | --- |
| Raspbian / Debian | chromium-headless-shell | chromium or google-chrome also works when available in `PATH` |
| All other Linux | chromium | devbox installs chromium on Linux; `chromium-headless-shell` is usually unavailable |
| macOS | Google Chrome | chromium on macOS/aarch64 is not considered stable; for devbox, install Chrome at `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome` |
| Windows | Chromium or Google Chrome | devbox installs chromium on WSL2; on native Windows (without WSL2), chromium or google-chrome should be in `PATH` |

InkyPi will search for a Chrome-like browser in the project's `PATH` (when using devbox) and then your system `PATH`.
