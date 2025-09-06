### Testing Plan for InkyPi

This document outlines the test strategy, scope, tooling, and rollout plan to establish reliable automated validation for InkyPi.

---

### Current State

- **No automated test suite** (no pytest/unittest). A manual visual script exists: `scripts/test_plugin.py`.
- **Architecture**: Flask app, background refresh thread, plugin system, display drivers, utilities.
- **External deps**: OpenWeatherMap/Open‑Meteo, OpenAI, Chromium headless screenshot, file uploads.

---

### Goals and Targets

- **Short‑term**: Foundational unit/integration tests for core logic; reproducible local runs; CI gate.
- **Medium‑term**: Stable plugin tests with external APIs mocked; API route tests; rendering mocked.
- **Coverage target**: Start at 60–70% over `src/`; later iterate to 80%+ on core logic (utils, model, scheduling).

---

### Tooling

- **Runner**: `pytest`
- **Web**: `pytest-flask` (optional; Flask testclient can suffice)
- **Coverage**: `pytest-cov`
- **Time control**: `freezegun`
- **HTTP mocks**: `requests-mock`
- **General mocks**: `unittest.mock`

Dev dependencies to be added to `install/requirements-dev.txt`:

```bash
pytest
pytest-cov
requests-mock
freezegun
pytest-flask
```

---

### Test Organization

```
tests/
  conftest.py                # shared fixtures: app, client, device_config, mock_screenshot
  unit/
    test_model.py            # PlaylistManager, PluginInstance, RefreshInfo
    test_image_utils.py      # resize_image, change_orientation, compute_image_hash
    test_app_utils.py        # parse_form, handle_request_files (with temp dirs)
    test_plugin_registry.py  # load_plugins, get_plugin_instance
  integration/
    test_refresh_task.py     # scheduling, manual update flow (mocks)
    test_plugin_routes.py    # /plugin/* endpoints via Flask client
  plugins/
    test_weather.py          # OWM & Open‑Meteo paths (requests mocked)
    test_ai_text.py          # OpenAI chat completions mocked
```

---

### Mocking and Fixtures Strategy

- **Rendering**: Monkeypatch `utils.image_utils.take_screenshot` to return a small in‑memory `PIL.Image` (no Chromium needed).
- **External APIs**: Mock `requests.get` (via `requests-mock`) and `OpenAI(...).chat.completions.create`.
- **Filesystem**: Use `tmp_path` for plugin image cache and uploads; monkeypatch `Config.config_file` to a temp JSON.
- **Time/Timezone**: Use `freezegun.freeze_time` with explicit tz awareness to validate schedule logic.
- **Environment**: Use `.env` values via monkeypatching `os.environ`, avoid real secrets.

Key shared fixtures (proposed `conftest.py`):

- `mock_screenshot` – patches `take_screenshot`/`take_screenshot_html` to return a blank image of requested dimensions.
- `device_config_dev` – loads a temp copy of `src/config/device_dev.json`, patches `Config.config_file` and output dirs.
- `flask_app` & `flask_client` – instantiate app from `src/inkypi.py` with background thread disabled for tests.

---

### What We Will Test First (High‑Value Targets)

1) Core scheduling and models (fast, deterministic)
- `PlaylistManager.should_refresh`
- `PlaylistManager.determine_active_playlist`
- `Playlist.get_time_range_minutes`
- `PluginInstance.should_refresh` and `get_image_path`

2) Utilities
- `image_utils.resize_image` (aspect/cropping rules), `change_orientation`, `compute_image_hash` determinism
- `app_utils.parse_form`, `handle_request_files` with temp images and EXIF paths

3) Plugin registry
- `load_plugins` instantiates classes from `plugin-info.json`; `get_plugin_instance` lookup behavior and error cases

4) Flask routes (happy/edge paths)
- `/plugin/<id>` loads settings template; 404 when not found; error surface when plugin raises
- `/update_now` with and without running refresh task; form parsing and file handling
- `/delete_plugin_instance` and `/display_plugin_instance` basic validation

5) Plugins (with mocks)
- `weather`: both providers (OpenWeatherMap/Open‑Meteo), units handling, timezone selection, error on non‑200
- `ai_text`: missing key error, request error surface, image generation path with mocked OpenAI

---

### Sample Assertions and Scenarios

- Scheduling: when last refresh is older than interval → refresh; otherwise skip.
- Playlist selection: overlapping windows prioritize smaller range; empty playlists yield no action.
- Image ops: resizing preserves target size; cropping rules obey `keep-width` setting; rotation orientation logic.
- Routes: form parsing merges file paths; correct HTTP status codes and JSON messages.
- Plugin output: generated `PIL.Image` has expected dimensions and non‑None content when mocks are in place.

---

### CI/CD

- GitHub Actions workflow:
  - `ubuntu-latest`, Python 3.10–3.12 matrix
  - Install `install/requirements.txt` and `install/requirements-dev.txt`
  - Run `pytest --maxfail=1 --disable-warnings -q`
  - Coverage gate: `--cov=src --cov-report=term-missing` (enforce threshold later)

---

### Rollout Plan (Milestones)

1) Infra (Day 1)
- Add dev deps; create `tests/` skeleton and fixtures; make tests runnable locally

2) Core unit tests (Day 1–2)
- `model.py`, `utils/image_utils.py`, `plugins/plugin_registry.py`

3) Integration tests (Day 2–3)
- `refresh_task` (manual update and interval flow), plugin routes

4) Plugin tests (Day 3–4)
- Weather providers; AI Text with OpenAI mocks

5) CI (Day 4)
- GitHub Actions workflow; optional coverage thresholds

---

### Open Questions

- Which Python versions should we officially support for CI (3.10/3.11/3.12)?
- Preferred initial coverage threshold (e.g., 60% now, 80% later)?
- Priority plugins beyond Weather and AI Text?
- Any tests to run on actual hardware, or mock only?
- OK to ignore Chromium dependency in tests by always mocking screenshot?

---

### How to Run (after setup)

```bash
pytest -q
pytest --cov=src --cov-report=term-missing
```


