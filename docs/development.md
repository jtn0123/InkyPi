# InkyPi Development Quick Start

## Development Without Hardware

The `--dev` flag enables complete development without requiring:

- Raspberry Pi hardware
- Physical e-ink displays (Inky pHAT/wHAT or Waveshare)
- Root privileges or GPIO access
- Linux-specific features (systemd)

Works on **macOS**, **Linux**, and **Windows** - no hardware needed!

## Setup

```bash
# 1. Clone and setup
git clone https://github.com/mudmin/InkyPi.git
cd InkyPi

# 2. Quick start (recommended)
./scripts/dev.sh

# Or manual setup
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r install/requirements-dev.txt
python src/inkypi.py --dev
```

**That's it!** Open `http://localhost:8080` and start developing.

## What You Can Do

- **Develop plugins** - Create new plugins without hardware (no Raspberry Pi, nor physical displays)
- **Test UI changes** - Instant feedback on web interface modifications  
- **Debug issues** - Full error messages in terminal
- **Verify rendering** - Check output in `mock_display_output/latest.png`
- **Cross-platform development** - Works on macOS, Linux, Windows

## Essential Commands

```bash
python src/inkypi.py --dev           # Start development server (full program)
python src/inkypi.py --dev --web-only# Start web UI only (no background thread)
python src/inkypi.py --dev --fast-dev# Fast cycle, skip startup image
./scripts/web_only.sh                # Scripted web-only startup
source venv/bin/activate             # Activate virtual environment
deactivate                           # Exit virtual environment
```

## Linting & Formatting

Ruff and Black are configured via `pyproject.toml`.

```bash
# Install dev dependencies (first time)
pip install -r install/requirements-dev.txt

# Check lint and formatting (no changes)
./scripts/lint.sh

# Auto-fix imports and format code
./scripts/format.sh
```

Notes:

- Ruff runs checks for pyflakes/pycodestyle/pyupgrade and sorts imports.
- Black enforces consistent formatting. Line length is 88.

## Development Tips

1. **Check rendered output**: Images are saved to `mock_display_output/`
2. **Plugin development**: Copy an existing plugin as template (e.g., `clock/`)
3. **Configuration**: Edit `src/config/device_dev.json` for display settings
4. **Hot reload**: You can run via Flask dev server for code reload

```bash
export FLASK_APP=src.inkypi:create_app
export INKYPI_ENV=dev
flask --debug run -p 8080
```

## Testing Your Changes

1. Configure a plugin through the web UI
2. Click "Display" button
3. Check `mock_display_output/latest.png` for result
4. Iterate quickly without deployment
