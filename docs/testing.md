### Testing Guide

This guide explains how to run, extend, and understand the test setup.

---

### Setup & Running

1) Create a venv and install deps
```bash
bash scripts/venv.sh
. .venv/bin/activate
python -m pip install -r install/requirements.txt || true   # hardware/system deps may fail on non-Pi
python -m pip install freezegun                           # required for time-freeze tests
```

2) Run tests
```bash
PYTHONPATH=$(pwd)/src pytest -q
PYTHONPATH=$(pwd)/src pytest --cov=src --cov-report=term-missing
```

Notes:
- Tests auto-mock Chromium image capture with a fixture; no browser required.
- Network calls to external APIs are mocked in plugin tests.

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

GitHub Actions runs tests and coverage across Python 3.10–3.12. Workflow file: `.github/workflows/tests.yml`.

---

### Adding New Tests

1) Place tests under `tests/` (unit, integration, or plugin subfolders).
2) Reuse fixtures from `conftest.py`.
3) Mock external APIs and I/O. Keep tests deterministic and fast.


