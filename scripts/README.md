# scripts/

Developer, CI and device tools. Run them from the repo root. Python scripts add
`src/` to the import path themselves.

## Everyday development

| Script | What it does |
|---|---|
| `dev.sh` | Creates the venv if needed and installs dev dependencies. |
| `venv.sh` | Sourced by the other scripts to activate the venv (adds a `python` shim when only `python3` exists). |
| `dev_environment.py` | Checks the active environment, or hash-verifies and syncs it (`--sync`). |
| `web_only.sh` | Starts the web UI without the refresh loop, using an ignored local device config. |
| `dev_watch.sh` | Watches `src/static/` and `src/templates/` and rebuilds assets on change (dispatches through `_dev_watch_dispatch.py`). |
| `seed_test_data.py` | Fills a dev install with sample plugin instances, playlists and history images. |
| `test.sh` / `test-fast.sh` | The test suite, and a faster local loop. |
| `test_profile.sh` | Runs pytest under a profiler (see `docs/profiling.md`). |
| `lint.sh` / `format.sh` | The lint gate CI runs (ruff, black, mypy, shellcheck, and locally Biome on the web scripts through the `biome-ci` pre-commit hook; CI's lint job runs Biome in its own step), and the auto-fixer. |
| `check_shell.sh` | `bash -n` and shellcheck (default severity) on every tracked shell script, found by extension and shebang; `lint.sh` runs it. |
| `precommit_browser_warning.sh` | Pre-commit hook: runs the browser smoke gate when front-end files change. |
| `precommit_tool.sh` | Pre-commit hook helper: runs ruff, black or mypy from the repo's `.venv` (or the main checkout's, inside a worktree), so hooks use the same versions as CI. |
| `extract_strings.py` | Extracts translatable strings into `translations/`. |
| `devbox_init.sh`, `devbox_renderer_smoke.py`, `devbox_verify_browser.sh` | Devbox setup, and a check that its Chromium renders plugins. |
| `container-env.sh` | Points the colima/lima CLIs at the VM used by the container scripts below. |

## Plugins and the display

| Script | What it does |
|---|---|
| `dry_run_plugin.py` | Renders one plugin to a PNG with no display, refresh loop or web server. `--record DIR` saves its HTTP responses; `--replay DIR` re-renders from them with no network or API calls. |
| `panel_preview.py` | Approximates how an image looks on a Spectra 6 panel: original, dithered and crisp side by side. |
| `calibration_pattern.py` | Generates e-ink calibration test patterns. |
| `image_diff.py` | Pixel-level comparison of two PNGs. |
| `compare_icons.py` | HTML matrix comparing the weather icons with a candidate icon pack. |
| `update_snapshots.py` | Regenerates the golden images for plugin snapshot tests. |
| `plugin_validator.py` | Checks each plugin folder: valid `plugin-info.json` with `id` and `class`, and the module file it needs. |
| `ui_audit.py` | Playwright screenshots of the main pages at desktop and mobile sizes, in light and dark. Run it against a running dev server. |

## Front-end assets

| Script | What it does |
|---|---|
| `build_css.py` | Flattens the CSS `@import` partials into `main.css`. |
| `build_assets.py` | Bundles and optionally minifies JS and CSS. |
| `update_cdn_sri.py` | Refreshes the SRI hashes in `cdn_manifest.json`. |

## CI gates and reports

| Script | What it does |
|---|---|
| `preflash_validate.sh` | The hardware-free pre-flash gate (wraps `preflash_smoke.py`). |
| `coverage_gate.py` | Per-file and per-package coverage floors for critical modules. |
| `perf_budget_gate.py` | Fails CI when the median plugin render or cold start goes over its ceiling. |
| `benchmark_compare.py` | Compares pytest-benchmark output against a stored baseline. |
| `memory_diff.py`, `format_memory_diff.py` | Startup memory profile for the per-PR memory diff comment. |
| `mutation_check.py`, `mutation_summary.py` | A small hand-written mutant check, and the summary for mutmut shards. |
| `check_licenses.sh` | Checks dependency licences with the `pip-licenses` pinned in `install/requirements-dev.txt` (installs nothing; run it from the dev venv). |
| `check_links.py` | Re-checks links that the Lychee link checker reported as throttled. |
| `check_requirements_drift.sh` | Checks that the exported lockfile matches `uv.lock`. |
| `check_vendor_versions.py` | Weekly check that the vendored front-end libraries (downloaded, CDN-loaded, and committed under `src/static/vendor/`) are current within their major (`vendor-versions.yml`). |
| `mypy_src_baseline.txt`, `mypy_tests_baseline.txt` | The mypy error ratchets used by `lint.sh`. |

## Install and Pi images

| Script | What it does |
|---|---|
| `sim_install.sh` + `Dockerfile.sim-install` | Runs `install/install.sh` in an arm64 container. |
| `Dockerfile.install-matrix` + `ci_install_matrix_verify.sh` | The CI install matrix: a full install in a container, then checks. |
| `test_install_memcap.sh` | Install smoke test under a 512 MB memory cap (Pi Zero 2 W). |
| `pi_image_manifest.py` | Raspberry Pi Imager metadata for the pinned Trixie image. |
| `verify_pi_image_boot.py` | Bounded QEMU userspace boot check of the image (not real hardware). |
| `cloud_init_clean.sh` | Resets cloud-init so edited `user-data` runs again on the next boot. |

## On the device

| Script | What it does |
|---|---|
| `logs.sh` | Shows or follows the service journal, locally or over SSH. |
| `dev_update.sh` | Pulls a branch (default `main`) on a dev Pi and restarts the service. `-r` hard-resets local changes. |
| `backup_config.py` / `restore_config.py` | Back up and restore the device config and plugin images as a tar.gz. |
| `diagnostic_snapshot.py` | Collects a support tarball, including the recent journal. |
| `diag_network.py` | Quick network diagnostics. |
| `validate_api_keys.py` | Probes the configured plugin API keys and reports which work. |
| `soak_runner.py` | The nightly soak run against a real Pi. |
