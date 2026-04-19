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
git clone https://github.com/jtn0123/InkyPi.git
cd InkyPi

# 2. Quick start (recommended)
./scripts/dev.sh

# Or manual setup
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

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
git clone https://github.com/jtn0123/InkyPi.git
cd InkyPi # direnv reads .envrc -> runs devbox shell -> installs deps & activates venv

# 3. Run InkyPi in developer mode via devbox
devbox run dev # alternatively run `devbox shell` and then run `python src/inkypi.py --dev`
```

</td>
</tr>
</table>

**That's it!** Open http://localhost:8080 and start developing.

### Install pre-commit hooks (recommended)

After cloning, install the git hooks so linting runs automatically before each commit:

```bash
pre-commit install
```

On every `git commit` this runs: whitespace/YAML/merge-conflict checks, **ruff** (lint + format),
**mypy** (type checks), **gitleaks** (secret scanning), and **conventional-commit** message
validation. See [`.pre-commit-config.yaml`](../.pre-commit-config.yaml) for the full hook list.

> **Bypass when needed:** `git commit --no-verify` skips the hooks locally, but CI enforces the
> same checks — failures will surface there instead.

## What You Can Do

- **Develop plugins** - Create new plugins without hardware (no Raspberry Pi, nor physical displays)
- **Test UI changes** - Instant feedback on web interface modifications
- **Debug issues** - Full error messages in terminal
- **Verify rendering** - Check output in `runtime/mock_display_output/latest.png`
- **Preview e-ink simulation** - Open `http://localhost:8080/dev/mock-frame` (dev mode only)
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

## Dev quick reference

Running commands for the tight edit-refresh loop:

```bash
# Start the Flask dev server (full program, auto-reloads Python + templates)
./scripts/dev.sh
# or:  .venv/bin/python src/inkypi.py --dev --web-only     # port 8080

# Auto-rebuild bundled CSS/JS on file changes (JTN-713)
./scripts/dev_watch.sh
#   watches src/static/styles/  → runs scripts/build_css.py
#   watches src/static/scripts/ → runs scripts/build_assets.py
#   watches src/templates/      → logs only (Flask auto-reloads templates)
# Requires `watchdog` (pip install watchdog). Ctrl+C exits cleanly.
# One-shot CSS build (no watcher):
python3 scripts/build_css.py
```

## Development Tips

1. **Check rendered output**: Images are saved to `runtime/mock_display_output/`
2. **Check simulated e-ink output**: latest frame is written to `/tmp/inkypi-mock-frame.png` (override with `INKYPI_MOCK_FRAME_PATH`)
3. **Plugin development**: Copy an existing plugin as template (e.g., `clock/`)
4. **Configuration**: Edit `src/config/device_dev.json` for display settings
5. **Hot reload**: You can run via Flask dev server for code reload. When `INKYPI_ENV=dev` or running with `--dev`, plugin modules are reloaded on access so you can iterate without restarting.

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
3. Check `runtime/mock_display_output/latest.png` for raw pre-driver result
4. Check `/tmp/inkypi-mock-frame.png` or `GET /dev/mock-frame` for simulated panel output
5. Iterate quickly without deployment
6. BasePlugin notes:
   - Jinja environment is initialized even if a plugin lacks its own `render/` directory. Base templates under `plugins/base_plugin/render/` are always available.
   - If a plugin does not provide `settings.html`, the UI will include `base_plugin/settings.html` by default.

## Docker (development)

For contributors who don't have a Pi, you can run InkyPi in a container:

```bash
docker compose up --build
```

The web UI will be available at http://localhost:8080. Source changes
in `src/` are reflected immediately via volume mount. The display is
automatically mocked — no hardware required.

To stop the container, press `Ctrl+C` or run `docker compose down`.

## CI Gate and Required Status Checks

The CI workflow includes a `ci-gate` job that depends on all required jobs — including
`lockfile-drift`, `security`, and `browser-smoke`. This job is the single handle the repo
owner should mark as a required status check in GitHub branch protection.

Frontend changes under `src/static/**` or `src/templates/**` also trigger the local
pre-commit browser gate, which runs `scripts/test.sh browser-smoke` before the commit is
allowed through.

### Making `ci-gate` a required status check (repo owner steps)

1. Go to **GitHub.com → jtn0123/InkyPi → Settings → Branches**.
2. Under "Branch protection rules", click **Edit** next to the `main` rule (or **Add rule**
   if none exists).
3. Enable **"Require status checks to pass before merging"**.
4. In the search box, type `CI gate` and select the check named
   **`CI gate (all checks pass)`**.
5. Also enable **"Require branches to be up to date before merging"** for extra safety.
6. Click **Save changes**.

Once saved, every PR must have a green `ci-gate` result before it can be merged. Because
`ci-gate` itself `needs: [lint, shellcheck, tests, sonarcloud, smoke, smoke-matrix,
coverage-gate, security, browser-smoke]`, any failure in any of those jobs will also fail
the gate.

> **Why a single gate job instead of listing each check?**
> GitHub's required-checks list is static — adding a new CI job requires a manual settings
> update. The gate pattern means you only ever need to protect one check name, and the
> `ci.yml` file controls which sub-jobs are required.

## Other Requirements

InkyPi relies on system packages for some features, which are normally installed via the `install.sh` script. **(Skip if using devbox method)**

### Linux

**(Skip this section if using devbox method)**

The required packages can be found in this file:

https://github.com/jtn0123/InkyPi/blob/main/install/debian-requirements.txt

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

## CodeQL suppression policy

CodeQL runs on every push and pull request. Most alerts represent real issues
and should be fixed in code. A small number are taint-tracker false positives
where CodeQL cannot model a validation/sanitization helper. When that happens,
suppress the alert at the flagged line with an `lgtm` comment, **always with a
specific justification**.

**Format**

- Python: `# lgtm[<rule-id>] — <why this is a false positive>`
- JavaScript: `// lgtm[<rule-id>] — <why this is a false positive>`

**Required**

1. Use the exact rule ID from the CodeQL alert (e.g. `py/clear-text-logging-sensitive-data`,
   `js/xss-through-dom`).
2. Include a justification after the em dash that explains *why* the alert
   does not apply to this specific call site. Reference the data flow,
   sanitization, or runtime invariant that makes the alert wrong.
3. Place the comment on the flagged line itself (not the line above or below)
   so CodeQL's suppression matcher picks it up.

**Forbidden**

- Generic comments like `# lgtm — false positive` or `# noqa`. They give
  the next maintainer no signal about whether the suppression is still valid.
- Suppressing a rule across an entire file or module unless every site has
  been audited and the rationale is documented in the policy section.
- Suppressing alerts in `src/blueprints/**` or `src/utils/http_utils.py`
  without coordinating with the JTN-318 cleanup; those files are still being
  hardened against raw exception strings in API responses.

**When in doubt**

If you are not sure whether an alert is a false positive, open a Linear issue
under the CodeQL epic (JTN-326) and tag it `security` rather than suppressing.
A real alert that is silenced by mistake is much worse than an unsuppressed
false positive that the dashboard learns to ignore.
