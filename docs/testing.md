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

### CI

GitHub Actions runs the pytest matrix and a required browser-smoke job. The main pytest job remains serial for now while the local xdist path soaks. Workflow file: `.github/workflows/ci.yml`.

---

### Adding New Tests

1) Place tests under `tests/` (unit, integration, or plugin subfolders).
2) Reuse fixtures from `conftest.py`.
3) Mock external APIs and I/O. Keep tests deterministic and fast.
