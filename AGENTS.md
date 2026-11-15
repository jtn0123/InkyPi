# Working on InkyPi

InkyPi is a Flask app that drives an e-ink picture frame on a Raspberry Pi
Zero 2 W (512 MB RAM). Start with `docs/architecture.md`; setup is in
`docs/development.md#setup`, and testing in `docs/testing.md`.

## Environment

- Python 3.13 only (Raspberry Pi OS Trixie). Don't add code paths or CI for
  other versions.
- `source scripts/venv.sh` creates and activates `.venv` with the locked,
  hash-checked dev requirements and sets `PYTHONPATH`.

## Tests

- Run tests with `scripts/test.sh` (whole suite, or `scripts/test.sh <path>`).
  It uses at most 4 xdist workers and runs the memory-sensitive tests
  serially afterwards.
- One test run at a time. Never `-n auto` or several suites in parallel:
  that has run the development Mac out of memory.
- Don't skip or delete a test because it fails; fix the cause.
- Browser tests (Playwright):
  - New browser test modules go in `UI_BROWSER_TESTS` in `tests/conftest.py`.
  - Wait for a condition, not a fixed time: `tests/unit/test_browser_wait_policy.py`
    rejects `page.wait_for_timeout` outside short polling loops.
  - Any `console.warn` or `console.error` fails the test (the client-log
    tripwire in `tests/integration/conftest.py`). Use `console.debug` for a
    failure the page already shows. A test that provokes a message on purpose
    declares it with `@pytest.mark.expected_client_logs(<regex>)`.

## Lint and format

- `scripts/lint.sh` is the gate: ruff, Black, mypy (strict; `tests/` and
  `scripts/` are held to the baselines in `scripts/mypy_tests_baseline.txt` and
  `scripts/mypy_scripts_baseline.txt`) and shellcheck. Biome
  lints the web scripts: `pre-commit run biome-ci --all-files`.
- Format Python with **Black**, not `ruff format`; they disagree and CI checks
  Black.
- `src/static/styles/main.css` is generated but committed. After editing a CSS
  partial, run `python scripts/build_css.py` and commit `main.css` too.

## Pull requests

- PR titles are Conventional Commits with a lowercase subject, for example
  `fix(playlist): wake the scheduler when playlists change`. CI checks this,
  and the title becomes the squash-merge commit on `main`.

## On a real device

- Some routes change state on GET. For example, `GET /api/blackout` turns
  blackout on. Only request routes you know are read-only.
- The service writes its in-memory settings back to
  `src/config/device.json`, so stop it (`sudo systemctl stop inkypi`) before
  editing that file by hand.
