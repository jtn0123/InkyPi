### Testing Guide

This guide explains how to run, extend, and understand the test setup.

---

### Setup & Running

1) Set up the environment as in [development.md → Setup](development.md#setup):
`source scripts/venv.sh` (in each new shell).

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
- With no args it runs `scripts/test-fast.sh`: the same tests as CI's `tests` job (`-m "not container"`), everything except the `memory` tests on 4 xdist workers (`INKYPI_TEST_WORKERS` overrides), then the `memory` tests serially. `tests/unit/test_local_test_runner.py` keeps the two passes matched to CI.
- Keep it to one run at a time, with 4 workers or fewer: `-n auto` or several suites at once has run the Mac out of memory.
- It runs a single explicit test file serially, and hands any other targets to `scripts/test-fast.sh`.
- Browser suites are skipped (`SKIP_BROWSER=1`) unless you target a single browser test file; they run in CI's `browser-smoke` and `browser-full` jobs.
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

- no_outside_network (autouse):
  - A test may only connect to this machine (loopback and Unix sockets). Any
    other connect or DNS lookup raises `NetworkBlocked`, an `OSError`, so the
    code under test behaves as if it were offline. The test then fails even if
    that code swallowed the error. Chromium runs in its own process and isn't
    covered.
  - Code that checks a URL resolves to a public address (image downloads, RSS,
    Calendar, Screenshot) needs `@pytest.mark.usefixtures("public_dns")`. That
    fixture answers every lookup with a public address without asking DNS.
    Stub the HTTP call as well.
  - Anything that builds the startup screen needs `lan_address`, which fixes
    the IP shown on it.
  - `@pytest.mark.allow_network` turns the guard off for one test. Nothing in
    the suite uses it.

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

### Simulating the device off-device

`tests/simulation/` runs device-shaped code paths on any machine with bash — no
Pi, no systemd, no container. The systemd notification socket is reproduced
rather than mocked (`sd_notify` is just a unix datagram), `systemctl` is a
recording shim on `PATH`, and the real `update.sh` / `boot-health.sh` /
`rollback.sh` run unmodified against a throwaway install tree.

```bash
SKIP_BROWSER=1 PYTHONPATH=src:. pytest -m simulation
```

This tier proves *our* logic against real protocols; it deliberately does not
simulate systemd's own behaviour (`Restart=`, `OnFailure=`, cgroups), which is
what the container gate below is for. **See [simulation.md](./simulation.md) for
the full boundary** — what is covered, what is not, and why.

---

### Pi thrash protection regression gate

`tests/integration/test_install_crash_loop.py` is the canonical regression gate for the "install crash mid-pip → restart loop" failure mode (JTN-609) that caused a real Pi Zero 2 W to require a hard power cycle on 2026-04-10.

The test boots a systemd-capable Debian container (`--privileged`, 512 MB cap), installs `inkypi.service` verbatim with a stub `ExecStart` that mimics `ModuleNotFoundError: flask`, runs `install.sh`'s `stop_service()` disable contract (JTN-600) and creates the `/var/lib/inkypi/.install-in-progress` lockfile (JTN-607), then repeatedly tries to start the service while the lockfile is present. The core invariant: **`ExecStart` must never run while the lockfile exists**. A marker file written by the stub is the primary assertion; if it appears, the defense is broken. A positive-control step removes the lockfile and confirms `ExecStart` does start once the install is "complete" so that the pass condition is not vacuous.

Running the gate locally:

```bash
# Requires a local Docker daemon. The test skips cleanly when Docker is
# absent or can't build or boot the container; set
# REQUIRE_INSTALL_CRASH_LOOP_TEST=1 to make each of those a failure instead
# (CI does).
PYTHONPATH=$(pwd)/src pytest tests/integration/test_install_crash_loop.py -v -s
```

The gate runs in under 60 s on a developer laptop and asserts three invariants:

1. JTN-600: after `stop_service()`, `systemctl is-enabled inkypi.service` is `disabled` or `masked`.
2. JTN-607: while the install-in-progress lockfile is present, `ExecMainPID=0` and the stub marker file is never touched — systemd's `ExecStartPre` refuses every start attempt.
3. The restart count stays bounded (`NRestarts <= 10`), proving systemd's default `StartLimitBurst` caps any runaway loop rather than thrashing the Pi's RAM.

If you are intentionally changing `install.sh`'s `stop_service()` function or `install/inkypi.service`'s `ExecStartPre` guard, expect this test to need updating — and be prepared to explain in the PR description how the Pi-thrash cascade (JTN-609 context) is still prevented.

The gate runs automatically in CI via the `install-crash-loop-gate` job (see `.github/workflows/ci.yml`), which sets `REQUIRE_INSTALL_CRASH_LOOP_TEST=1` so every skip fallback (no Docker, image build failed, container or systemd didn't start) fails instead, for both container modules. It is listed in the `ci-gate` required-success loop, so a regression will block merge (JTN-614).

---

### CI

GitHub Actions runs the pytest matrix, pre-flash validation matrix, coverage gate, security/SBOM checks, flake detection, and the browser-smoke job. Nightly scheduled jobs run the soak and mutation lanes on Linux. The main pytest job remains serial for now while the local xdist path soaks. Workflow file: `.github/workflows/ci.yml`.

---

### CI memory budgets

The `install-smoke-memcap` job (`scripts/test_install_memcap.sh`, Phase 4) asserts the running web service stays within the Pi Zero 2 W memory envelope. Budgets map to the hardware: the Pi Zero 2 W has 512 MB RAM, of which the kernel reports about 426 MiB (`MemTotal`), shared with the OS and Chromium renders. Nothing caps InkyPi's memory there: the `memory.conf` drop-in sets `MemoryHigh=350M` and `MemoryMax=500M`, but Raspberry Pi OS boots with `cgroup_disable=memory`, so systemd can't apply them (`memory_controller.active` in `/api/diagnostics` shows whether it can). When memory runs out, earlyoom kills a process, preferring Chromium's. So a PR that ships an idle RSS of ~250 MB passes the install step but runs the Pi out of memory on real hardware.

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

### OS drift nightly (JTN-535)

`.github/workflows/os-drift-nightly.yml` runs daily at 08:00 UTC against the unpinned Trixie base — the only supported installer target, since InkyPi requires Python 3.13 (`python-next.yml` runs the tests weekly on Python 3.14 as an early warning; it gates nothing). Bookworm (Python 3.11) and Bullseye (Python 3.9) are no longer probed. Package discovery runs natively on ARM64 with the same simulation-only Pi OS repository overlay as the installer simulator; resolver checks verify hashes and the install simulation still runs with a 512 MB cap. Container commands select bash explicitly. Failures publish a job summary and artifacts; repositories with Issues enabled also receive the existing issue notification. The nightly has no PR trigger. Dispatch the feature branch to validate changes, and keep package errors distinct from harness failures. These are simulation checks, not physical display/GPIO evidence.

---

### Random test order

`pytest-randomly` is installed, but it is off by default (`pytest.ini` has `-p no:randomly`). A test that only passes in one order hides state leaks, so run the suite shuffled when you change shared state. Turn it on with `-p randomly`:

```bash
PYTHONPATH=src:. SKIP_BROWSER=1 pytest -p randomly
```

The header prints `Using --randomly-seed=N`. To replay a failing order, pass the same seed: `pytest -p randomly --randomly-seed=N <file>`. `.github/workflows/random-order-nightly.yml` runs the suite shuffled every night, without browsers.

### tests/static ratchet

`tests/static/` holds tests that grep JS and CSS source text instead of driving the page. They miss real behaviour, so new ones are not allowed. `tests/unit/test_static_text_tests_ratchet.py` counts the `test_*.py` files there and fails if the count goes up. Write a Playwright test in `tests/integration/` instead. The test also fails if the count goes down, so lower `CEILING` in that file to the new count.

---

### Adding New Tests

1) Place tests under `tests/` (unit, integration, or plugin subfolders).
2) Reuse fixtures from `conftest.py`.
3) Mock external APIs and I/O. Keep tests deterministic and fast.
