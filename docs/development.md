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
Setup with a virtual environment (macOS, Linux, or WSL2 on Windows)

```bash
git clone https://github.com/jtn0123/InkyPi.git
cd InkyPi
source scripts/venv.sh       # makes .venv on Python 3.13 and installs the
                             # locked, hash-checked dev requirements
./scripts/dev.sh --web-only  # web UI only; drop --web-only to also run the
                             # refresh loop against the mock display
```

`source scripts/venv.sh` is the whole setup: run it in each new shell. It
creates `.venv` with Python 3.13 if it's missing, activates it, installs
`install/requirements-dev.txt` with `--require-hashes` when the installed
packages have drifted, and sets `PYTHONPATH`. An unchanged environment takes a
check-only fast path. To inspect the environment without installing anything,
run `python scripts/dev_environment.py`.

A new environment gets uv first (pip installs it from
`install/uv-requirements.txt`, hash-checked), and uv then installs the dev
requirements, which takes seconds rather than pip's minutes. In a git worktree
that has no `.venv`, `scripts/venv.sh` uses the main checkout's `.venv`
instead, when that venv was synced from exactly the worktree's
`install/requirements-dev.txt` on Python 3.13 (`dev_environment.py
--require-stamp`). It never syncs that venv from the worktree: once the
worktree's lock differs, the worktree builds its own `.venv`.
`INKYPI_OWN_VENV=1` always builds one.

The compiled stylesheet (`src/static/styles/main.css`) and the vendored
htmx/Leaflet files are committed, so nothing else needs building. After editing
CSS, run `python scripts/build_css.py` (or `./scripts/dev_watch.sh`, below) and
commit the rebuilt `main.css`. A width `@media` query must use one of the four
breakpoint tokens listed in `partials/_tokens.css` (640, 768, 900 and 1200px,
as `max-width: N` or `min-width: N+1`); the build warns about any other width
and `tests/unit/test_css_breakpoints.py` fails on it.

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

After cloning, install the git hooks. One command installs all three hook types
(`pre-commit`, `commit-msg` and `pre-push`):

```bash
pre-commit install
```

On every `git commit` this runs: whitespace/YAML/merge-conflict checks, **ruff** (lint),
**black** (format), **mypy** on `src/`, **Biome** (lint of the web scripts, see below),
**gitleaks** (secret scanning of the staged changes), and, when a stylesheet partial changed,
`scripts/build_css.py` to rebuild `main.css`. The commit-msg hook then checks the message is a
Conventional Commit. Ruff, Black and mypy run from `.venv`, so they are the same pinned
versions `scripts/lint.sh` and CI use. See [`.pre-commit-config.yaml`](../.pre-commit-config.yaml)
for the full hook list.

Before a `git push` whose commits change `src/static/` or `src/templates/`, the pre-push hook
runs the browser smoke gate (`scripts/test.sh browser-smoke`, about 45 seconds). It's skipped
with a message when Playwright Chromium isn't installed; CI's browser-smoke job runs it on every
pull request either way. If you installed the hooks before the pre-push stage existed, run
`pre-commit install` again to add it.

> **Bypass when needed:** `git commit --no-verify` skips the hooks locally, but CI enforces the
> same checks: the lint job runs `scripts/lint.sh`, Biome on every web script, and the hygiene
> hooks on the files your change touches, and gitleaks has its own workflow.

### Linting the web scripts (Biome)

The web UI's JavaScript (`src/static/scripts/` and the service worker, `src/static/sw.js`) is
linted by [Biome](https://biomejs.dev).
There is no build step and no `package.json`: the pre-commit hook uses Biome's official mirror,
which installs the pinned Biome into pre-commit's own cache, and CI's lint job installs the same
version. Biome only lints; its formatter is off, so it never rewrites a file.

```bash
pre-commit run biome-ci --all-files   # every script, the same check CI runs
```

`scripts/lint.sh` runs the same command, so a passing local lint means a passing CI lint job.

[`biome.json`](../biome.json) holds the rules: Biome's recommended `correctness`, `suspicious`
and `security` rules plus `noUndeclaredVariables` and `noUnusedVariables`, with warnings failing
the check. Biome reads each file as a module, so two things need care in these classic scripts:

- A function another script calls by **bare name** (`showResponseModal(...)`) goes in
  `javascript.globals` in `biome.json`, and its defining script assigns it to `globalThis`
  (see the end of `response_modal.js`). Globals read as `window.X` / `globalThis.X` need no entry.
- `noRedundantUseStrict` is off: `"use strict"` is not redundant in a classic script.

Fix a finding rather than suppressing it. When a suppression really is needed, use
`// biome-ignore lint/<group>/<rule>: <specific reason>` on the line above.

To bump Biome, change the version in `biome.json` (`$schema`), the hook's `rev` in
`.pre-commit-config.yaml` and the `setup-biome` input in `.github/workflows/ci.yml` together;
`tests/unit/test_biome_config.py` fails if they disagree.

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
source .venv/bin/activate            # Activate virtual environment
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
# Start the dev server (full program; edited page templates show on the next
# request, Python changes need a restart: Ctrl+C and run it again)
./scripts/dev.sh
# or:  .venv/bin/python src/inkypi.py --dev --web-only     # port 8080

# Auto-rebuild bundled CSS/JS on file changes (JTN-713)
./scripts/dev_watch.sh
#   watches src/static/styles/  → runs scripts/build_css.py
#   watches src/static/scripts/ → runs scripts/build_assets.py
#   watches src/templates/      → logs only (dev mode re-reads templates)
# Requires `watchdog` (pip install watchdog). Ctrl+C exits cleanly.
# One-shot CSS build (no watcher):
python3 scripts/build_css.py
```

## Development Tips

1. **Check rendered output**: Images are saved to `runtime/mock_display_output/`
2. **Check simulated e-ink output**: latest frame is written to `/tmp/inkypi-mock-frame.png` (override with `INKYPI_MOCK_FRAME_PATH`)
3. **Plugin development**: Copy an existing plugin as template (e.g., `clock/`)
4. **Configuration**: Edit `src/config/device_dev.json` for display settings
5. **What reloads in dev mode** (`--dev` or `INKYPI_ENV=dev`): a plugin's Python module is reloaded each time the plugin is used (set `INKYPI_NO_HOT_RELOAD=1` to turn this off), and page templates are re-read on the next request. Any other Python change needs a restart.

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

The web UI will be available at http://localhost:8080. The display is
mocked, so no hardware is needed.

`docker-compose.yml` mounts `src/` into the container read-only and runs the
app in dev mode, so the same rules apply as in
[Development Tips](#development-tips): templates are re-read on the next
request, and a plugin's Python module is reloaded the next time the plugin
runs. Any other Python change needs `docker compose restart`. The container
also sets `INKYPI_NO_REFRESH=1`, so the refresh loop doesn't run; use a
plugin's **Update Now** button to render.

To stop the container, press `Ctrl+C` or run `docker compose down`.

## CI Gate and Required Status Checks

The CI workflow includes a `ci-gate` job, named **`CI gate (all checks pass)`**, that
depends on all required jobs, including the install gates. It is the single check `main`
requires.

Frontend changes under `src/static/**` or `src/templates/**` also trigger the local
pre-push browser gate, which runs `scripts/test.sh browser-smoke` before the push goes
through (see [Install pre-commit hooks](#install-pre-commit-hooks-recommended)).

### Making `ci-gate` a required status check (repo owner steps)

`main` is protected by a repository ruleset, **main: require the CI gate**, not a classic
branch-protection rule. The release workflow pushes its version-bump commit and tag
straight to `main` (see [Releases](#releases)). That commit never has CI results of its
own, so a required check would reject it, and the ruleset lets the release deploy key
bypass the check.

1. Go to **GitHub.com → jtn0123/InkyPi → Settings → Rules → Rulesets**, and create a
   branch ruleset (or edit the existing one) that targets the default branch, `main`.
2. Set **Enforcement status** to **Active**.
3. Enable **Require status checks to pass**, and add the check
   **`CI gate (all checks pass)`**.
4. Leave **Require branches to be up to date before merging** off. With it on, every pull
   request would have to be rebased after each release commit.
5. Under **Bypass list**, add the release deploy key (**Deploy keys**) and nothing else.
6. Click **Create** (or **Save changes**).

Once saved, every PR must have a green `ci-gate` result before it can be merged. Because
`ci-gate` mirrors the required-job list in `.github/workflows/ci.yml`, any required-job
failure will also fail the gate.

> **Why a single gate job instead of listing each check?**
> GitHub's required-checks list is static — adding a new CI job requires a manual settings
> update. The gate pattern means you only ever need to protect one check name, and the
> `ci.yml` file controls which sub-jobs are required.

## Releases

`.github/workflows/release.yml` runs when CI passes for a push to `main`, and only for the
commit CI tested. A release stays a draft until every file is attached to it:

1. **Tag the release** runs `semantic-release version --no-vcs-release`. It picks the next
   version from the commit subjects, updates `pyproject.toml`, `VERSION`, `uv.lock` and
   `CHANGELOG.md`, then commits, tags and pushes. The push goes over the release deploy key
   (the `RELEASE_DEPLOY_KEY` Actions secret, which `actions/checkout` configures), because
   `[tool.semantic_release.remote] ignore_token_for_push` keeps a token out of the push
   URL. The commit message carries `[skip ci]`, so the version-only commit doesn't run CI or
   start another release.
2. **Create the draft release** creates the GitHub release as a draft, with the notes
   semantic-release generates from `templates/.release_notes.md.j2`.
3. **Attach the SBOM**, **Build wheelhouse release assets** (`build-wheelhouse.yml`) and
   **Build pre-installed Pi image** (`build-pi-image.yml`) attach their files to the
   draft. Each one uploads only to a draft.
4. **Publish the release** runs only after all three succeed. It checks that every file is
   on the draft, then publishes it and marks it latest. If a higher version is already
   published, because an older release run finished last, it stays latest instead.

A Pi's update check reads `/releases/latest`, which never returns a draft, and a draft's
download URLs return 404. With no tag given, `do_update.sh` (which the Update button runs)
installs the release `/releases/latest` names, not the newest tag, which a draft already
has. Only when it can't ask GitHub does it fall back to the newest tag. After a release is
published, GitHub's immutable releases stop its files and tag from changing.

### When a release job fails

If an asset job fails, the release stays a draft, and the tag stays on `main`. Re-run the
failed jobs from the Release run's page (**Re-run failed jobs**). Uploads replace files of
the same name, so a re-run doesn't add duplicates, and **Publish the release** runs again
once they pass. Don't re-run all jobs: the gate then finds `main` has moved past the tested
commit and skips everything.

A re-run uses the workflow files of the original run. If the failure needs a change to a
workflow, merge the fix with a type that doesn't cut a release, such as `ci:`. Then attach
the missing files by hand and publish:

- Run **Build release wheelhouse** or **Build pre-installed Pi image** from the Actions
  tab for the release's tag. Both attach to a release only while it is a draft.
- The SBOM has no manual workflow. Build it the way the **Attach the SBOM** job does (at the
  tag, from a venv holding only `install/requirements.txt`), and upload it with
  `gh release upload vX.Y.Z inkypi-vX.Y.Z-bom.json --clobber`.
- Check that the draft has the SBOM, both wheelhouse architectures (the tarball, its
  `.sha256` and its `.manifest.sha256`) and the image (the `.img.xz`, its `.sha256` and the
  `-os-list.json` manifest). Then publish it with
  `gh release edit vX.Y.Z --draft=false --latest`.

If **Tag the release** fails after its push, a re-run stops at "Confirm main is still the
tested commit". Create the draft yourself with
`gh release create vX.Y.Z --draft --verify-tag --title vX.Y.Z`, using that version's
`CHANGELOG.md` section as the notes, and attach the files as above.

### Manual rechecks

Both asset workflows can be run by hand for any tag. For a published release they only
build: the wheelhouse and the image stay as artifacts of that run, because a published,
immutable release can't take new files. A Pi image run with `reuse_run_id` only
boot-verifies an image from an earlier run, and never attaches it.

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

CodeQL runs on every pull request to `main`, on every push to `main`, and
weekly. Most alerts represent real issues and should be fixed in code. A
small number are taint-tracker false positives where CodeQL cannot model a
validation or sanitization helper.

GitHub code scanning ignores `# lgtm[...]` comments (they were an LGTM.com
feature), so don't add them. To close a false positive, dismiss the alert in
**Security → Code scanning**:

1. Pick the reason that fits: **False positive**, **Used in tests**, or
   **Won't fix**.
2. In the comment, say *why* the alert does not apply to this call site:
   the data flow, sanitization, or runtime invariant that makes it wrong.
   "False positive" on its own gives the next maintainer nothing to check.

A dismissal applies to that one alert. If the code moves and CodeQL raises
it again, dismiss the new alert with the same reasoning, or fix the code so
CodeQL can follow the check.

**When in doubt**

If you are not sure whether an alert is a false positive, open a Linear issue
under the CodeQL epic (JTN-326) and tag it `security` rather than dismissing it.
A real alert that is dismissed by mistake is much worse than an open false
positive.
