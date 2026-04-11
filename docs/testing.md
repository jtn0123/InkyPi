### Testing Guide

This guide explains how to run, extend, and understand the test setup.

---

### Setup & Running

1) Create a venv and install deps
```bash
bash scripts/venv.sh
. .venv/bin/activate
python -m pip install -r install/requirements.txt -r install/requirements-dev.txt || true
```

2) Run tests
```bash
scripts/test.sh
scripts/test.sh tests/unit/test_refresh_task_stress.py
scripts/test_profile.sh
scripts/preflash_validate.sh
PYTHONPATH=$(pwd)/src pytest -q
PYTHONPATH=$(pwd)/src pytest --cov=src --cov-report=term-missing
```

Notes:
- `scripts/test.sh` is the recommended fast local path.
- `scripts/preflash_validate.sh` is the recommended hardware-free pre-flash gate.
- With no args it shards the main local suite across 4 lanes (`core`, `plugins-a`, `plugins-b`, `plugins-c`) and uses `PYTEST_LANE_WORKERS=2` per lane by default.
- It runs serial for a single explicit test file and uses `pytest -n 4 --dist=loadfile -q` for broader explicit targets.
- The default fast path keeps Playwright-backed UI/a11y suites explicit so normal local runs avoid browser startup overhead.
- Use `PYTHONPATH=$(pwd)/src pytest -q` for serial debugging or when investigating xdist-only issues.
- Coverage runs remain serial for now while the parallel local path soaks.
- `scripts/test_profile.sh` profiles the slowest tests with `--durations=25` and defaults to `tests/plugins`.
- Tests auto-mock Chromium image capture with a fixture; no browser required.
- Managed API-key env vars are cleared per test and the temp test `PROJECT_DIR` gets an empty `.env`, which keeps missing-key flows local and deterministic.
- Browser smoke coverage is separate and requires Playwright Chromium:
  - `playwright install chromium`
  - `PYTHONPATH=$(pwd)/src REQUIRE_BROWSER_SMOKE=1 pytest tests/integration/test_browser_smoke.py -q`
- Pre-flash validation works without the device connected and checks app boot, config resolution, mock rendering, and targeted pytest coverage.
- Set `INKYPI_VALIDATE_INSTALL=1` to include the import-only install smoke phase; it runs in a clean temporary environment on both macOS and Linux, and Linux additionally validates the Inky/systemd-related imports.
- Additional opt-in lanes are available via env flags on `scripts/preflash_validate.sh`:
  - `INKYPI_VALIDATE_PI_RUNTIME=1`
  - `INKYPI_VALIDATE_STRESS=1`
  - `INKYPI_VALIDATE_HEAVY_PLUGINS=1`
  - `INKYPI_VALIDATE_BENCH_THRESHOLDS=1`
  - `INKYPI_VALIDATE_COLD_BOOT=1`
  - `INKYPI_VALIDATE_CACHE=1`
  - `INKYPI_VALIDATE_ISOLATION=1`
  - `INKYPI_VALIDATE_BROWSER_RENDER=1`
  - `INKYPI_VALIDATE_INSTALL_IDEMPOTENCY=1`
  - `INKYPI_VALIDATE_FAULTS=1`
  - `INKYPI_VALIDATE_UPGRADE_COMPAT=1`
  - `INKYPI_VALIDATE_COVERAGE=1`
  - `INKYPI_VALIDATE_SECURITY=1`
  - `INKYPI_VALIDATE_FLAKE=1`
  - `INKYPI_VALIDATE_FS_PERMS=1`
  - `INKYPI_VALIDATE_SOAK=1`
  - `INKYPI_VALIDATE_RECOVERY=1`
  - `INKYPI_VALIDATE_API_CONTRACT=1`
  - `INKYPI_VALIDATE_MUTATION=1`
- The new hardening lanes cover fault injection, property/invariant regression, upgrade compatibility for legacy config and benchmark DBs, per-file coverage thresholds, security audit plus SBOM output, flaky-test reruns, readonly filesystem handling, startup recovery, API contracts, nightly soak, and a narrow deterministic mutation harness.
- Pre-flash validation does not prove EEPROM detection, SPI/GPIO access, or real panel refresh; those are post-flash hardware checks.
- A11y/browser suites can still be run explicitly:
  - `PYTHONPATH=$(pwd)/src SKIP_A11Y=0 pytest tests/integration/test_more_a11y.py -q`
  - `PYTHONPATH=$(pwd)/src SKIP_UI=0 pytest tests/integration/test_weather_autofill.py -q`
  - `PYTHONPATH=$(pwd)/src SKIP_UI=0 SKIP_A11Y=0 pytest tests/integration/test_browser_smoke.py tests/integration/test_more_a11y.py -q`
- If a removed UI element such as the old skip link still appears in the browser after code changes, refresh the page or restart the app; stale server/browser state can mask template updates.

---

### Key Fixtures (tests/conftest.py)

- mock_screenshot (autouse):
  - Patches `utils.image_utils.take_screenshot` and `take_screenshot_html` to return an in-memory `PIL.Image` of the requested size.
  - Ensures tests run fast and hardware-free.

- device_config_dev:
  - Creates a temp `device.json` and patches `Config` paths to point to temporary locations.
  - Keeps file IO and plugin image cache isolated.

- flask_app, client:
  - Builds a minimal Flask app mirroring production blueprints and config.
  - Exposes a `test_client` for endpoint tests.

---

### Test Coverage Focus

- Unit tests
  - `model.py`: scheduling, playlist priorities, plugin refresh logic
  - `utils/image_utils.py`: orientation, resize, image hashing
  - `plugins/plugin_registry.py`: load and lookup

- Integration tests
  - Settings routes, plugin routes, refresh task manual update flow

- Plugins
  - Weather: OpenWeatherMap & Open‑Meteo paths mocked
  - AI Text: OpenAI chat completions mocked
  - AI Image: OpenAI image generation mocked

---

### OpenAI Image Quality Mapping

To align with current API behavior:
- `dall-e-3`: quality `standard` or `hd`
- `gpt-image-1`: quality `standard` or `high`

UI updates:
- The AI Image settings present `standard/hd` for DALL·E 3 and `standard/high` for GPT Image 1.

Server-side normalization:
- The app normalizes any input (e.g., `low`, `medium`, `hd`, `high`) to valid values per model before calling the API.

---

### Pi thrash protection regression gate

`tests/integration/test_install_crash_loop.py` is the canonical regression gate for the "install crash mid-pip → restart loop" failure mode (JTN-609) that caused a real Pi Zero 2 W to require a hard power cycle on 2026-04-10.

The test boots a systemd-capable Debian container (`--privileged`, 512 MB cap), installs `inkypi.service` verbatim with a stub `ExecStart` that mimics `ModuleNotFoundError: flask`, runs `install.sh`'s `stop_service()` disable contract (JTN-600) and creates the `/var/lib/inkypi/.install-in-progress` lockfile (JTN-607), then repeatedly tries to start the service while the lockfile is present. The core invariant: **`ExecStart` must never run while the lockfile exists**. A marker file written by the stub is the primary assertion; if it appears, the defense is broken. A positive-control step removes the lockfile and confirms `ExecStart` does start once the install is "complete" so that the pass condition is not vacuous.

Running the gate locally:

```bash
# Requires a local Docker daemon. The test skips cleanly when Docker is
# absent; set REQUIRE_INSTALL_CRASH_LOOP_TEST=1 to force-run and fail hard
# if Docker is missing (useful in CI).
PYTHONPATH=$(pwd)/src pytest tests/integration/test_install_crash_loop.py -v -s
```

The gate runs in under 60 s on a developer laptop and asserts three invariants:

1. JTN-600: after `stop_service()`, `systemctl is-enabled inkypi.service` is `disabled` or `masked`.
2. JTN-607: while the install-in-progress lockfile is present, `ExecMainPID=0` and the stub marker file is never touched — systemd's `ExecStartPre` refuses every start attempt.
3. The restart count stays bounded (`NRestarts <= 10`), proving systemd's default `StartLimitBurst` caps any runaway loop rather than thrashing the Pi's RAM.

If you are intentionally changing `install.sh`'s `stop_service()` function or `install/inkypi.service`'s `ExecStartPre` guard, expect this test to need updating — and be prepared to explain in the PR description how the Pi-thrash cascade (JTN-609 context) is still prevented.

The gate runs automatically in CI via the `install-crash-loop-gate` job (see `.github/workflows/ci.yml`), which sets `REQUIRE_INSTALL_CRASH_LOOP_TEST=1` so the skip-without-Docker fallback is force-disabled. It is listed in the `ci-gate` required-success loop, so a regression will block merge (JTN-614).

---

### CI

GitHub Actions runs the pytest matrix, pre-flash validation matrix, coverage gate, security/SBOM checks, flake detection, and the browser-smoke job. Nightly scheduled jobs run the soak and mutation lanes on Linux. The main pytest job remains serial for now while the local xdist path soaks. Workflow file: `.github/workflows/ci.yml`.

---

### CI memory budgets

The `install-smoke-memcap` job (`scripts/test_install_memcap.sh`, Phase 4) asserts the running web service stays within the Pi Zero 2 W memory envelope. Budgets map to the hardware: the Pi Zero 2 W has 512 MB RAM and the systemd unit caps InkyPi at `MemoryMax=350M`, so a PR that ships an idle RSS of ~250 MB passes the install step but OOMs on real hardware.

The checks run inside the 512 MB-capped Phase 3 container and read `VmRSS` from `/proc/1/status` (the `CMD` python process). Both failures print a `BUDGET CHECK:` line to the CI log so regressions are easy to grep for.

| Metric | Target | Hard fail | Tracked by |
| --- | --- | --- | --- |
| Post-install idle RSS (30s after `/healthz`) | <150 MB | >200 MB | JTN-608 |
| Peak RSS during plugin render exercise | <250 MB | >300 MB | JTN-608 |

Notes:
- Phase 4 sleeps 30s before the idle sample, then hits `/`, `/playlist`, `/api/plugins`, `/api/health/plugins`, and a `POST /update_now` with `plugin_id=clock` to exercise the render codepath. `--web-only` mode short-circuits the actual refresh, but the request still drives the hottest allocation path (form parsing, plugin import, response build).
- If you add a plugin or import that pushes baseline RSS above the target, bump the plugin's lazy-import boundary rather than raising the budget.
- The 100-request memory-growth leak check from the JTN-608 ticket is intentionally deferred; the two-sample idle/peak gate catches the class of regressions we care about at PR time without adding minutes to CI.

---

### Adding New Tests

1) Place tests under `tests/` (unit, integration, or plugin subfolders).
2) Reuse fixtures from `conftest.py`.
3) Mock external APIs and I/O. Keep tests deterministic and fast.
