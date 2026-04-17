# Plugin Snapshot (Golden-File) Tests

This directory holds golden-file baselines for plugin `generate_image()` outputs.
Each snapshot baseline is a canonical PNG:

```
tests/snapshots/<plugin_name>/<case_name>.png     # canonical image for comparison + review
```

## How it works

1. A test freezes all non-deterministic inputs (time, network calls, random seeds).
2. It calls `plugin.generate_image(settings, device_config)`.
3. `assert_image_snapshot(result, plugin_name, case_name)` performs a pixel diff
   against the stored baseline PNG.
4. If the diff is within tolerance → pass. If not → fail and emit:
   - `tests/snapshots/actual/<plugin>/<case>.png` (actual output)
   - `tests/snapshots/actual/<plugin>/<case>.diff.png` (red overlay of changed pixels)
   - `tests/snapshots/actual/<plugin>/<case>.diff.json` (counts + thresholds)

## Browser requirement

The plugins under test render HTML→PNG via Playwright Chromium.  Without a
working browser, `base_plugin.py`'s `_screenshot_fallback()` returns a blank
white canvas — every plugin produces the same bytes, and the "test" degrades
into a meaningless no-op.

Because of this, the snapshot tests are gated on `REQUIRE_BROWSER_SMOKE=1`
(the same env var the browser-smoke CI job uses):

| Environment                       | Runs snapshot tests? |
|-----------------------------------|----------------------|
| Main `Tests (pytest)` CI matrix   | collected but **skipped** — no `REQUIRE_BROWSER_SMOKE`, no browser |
| `Browser smoke` CI job            | **yes** — sets `REQUIRE_BROWSER_SMOKE=1`, Chromium installed |
| Local dev without the env var     | skipped with a clear reason |
| Local dev with `REQUIRE_BROWSER_SMOKE=1` + `playwright install chromium` | runs |

## Running the snapshot tests locally

```bash
# One-time: install Playwright browsers
.venv/bin/python -m playwright install chromium

# Then run:
REQUIRE_BROWSER_SMOKE=1 .venv/bin/python -m pytest tests/snapshots/ -v
```

Note: baselines are captured on Linux x86_64 in the same env as the
`browser-smoke` CI job.  Running on macOS or another Linux distro may produce
different PNG bytes because Chromium's font fallback picks up different
system fonts — when in doubt, regenerate via the docker command below.

## Updating baselines (intentional changes)

Because baselines are sensitive to Chromium's system-font fallback, regenerate
them **inside an `ubuntu:24.04` docker container** — the same base image that
GitHub Actions' `ubuntu-latest` currently resolves to.  Debian-bookworm or
`python:3.12-slim-*` images have different default fonts and will produce
baselines that fail on CI.  From the project root:

```bash
docker run --rm --platform linux/amd64 -v "$(pwd):/app" -w /app \
  ubuntu:24.04 bash -c '
    set -e
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y --no-install-recommends -qq \
      python3 python3-venv python3-pip python3-dev ca-certificates \
      libopenjp2-7 libopenblas-dev libfreetype6-dev fonts-noto-color-emoji \
      build-essential libjpeg-dev zlib1g-dev
    python3 -m venv /tmp/venv
    . /tmp/venv/bin/activate
    pip install --no-cache-dir -r install/requirements.txt \
                               -r install/requirements-dev.txt
    python -m playwright install --with-deps chromium
    REQUIRE_BROWSER_SMOKE=1 INKYPI_ENV=dev INKYPI_NO_REFRESH=1 PYTHONPATH=src \
      python -m pytest tests/snapshots/ -v --update-snapshots
  '
```

After the run, commit the updated `tests/snapshots/<plugin>/*.png` files.

> `scripts/update_snapshots.py` still works for running inside a properly
> set-up environment (local venv with chromium, or the Pi). It is a thin
> wrapper around `pytest ... --update-snapshots`.

## Adding snapshots for a new plugin

1. Write a test in `tests/snapshots/test_plugin_snapshots.py` (or a new file in
   this directory) that:
   - Freezes time / mocks network calls so the output is deterministic.
   - Calls `assert_image_snapshot(result, "<plugin_name>", "<case_name>")`.
2. Regenerate baselines via the docker command above.
3. Verify the new `.png` files contain **real rendered content** (not a blank
   white canvas) before committing — if they're blank, Chromium isn't
   actually rendering and you need to debug the environment before trusting
   the baseline.
4. Commit the `.png` files alongside the test.

## Design decisions

- **Pixel-based comparison** — snapshots compare rendered pixels with configurable
  tolerance:
  - `SNAPSHOT_CHANNEL_THRESHOLD` (default `6`) for per-channel delta.
  - `SNAPSHOT_MAX_CHANGED_PCT` (default `0.05`) for changed-pixel percentage.
- **No `pytest-snapshot` dep** — a tiny custom helper avoids adding a new package
  to the lockfile and keeps the comparison logic transparent.
- **PNG binaries** — `.gitattributes` marks `tests/snapshots/**/*.png` as binary so
  git doesn't try to diff them as text.
