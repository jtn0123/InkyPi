# Plugin Snapshot (Golden-File) Tests

This directory holds golden-file baselines for plugin `generate_image()` outputs.
Each snapshot consists of two files:

```
tests/snapshots/<plugin_name>/<case_name>.png     # canonical image for human review
tests/snapshots/<plugin_name>/<case_name>.sha256  # SHA-256 hex digest (what tests compare)
```

## How it works

1. A test freezes all non-deterministic inputs (time, network calls, random seeds).
2. It calls `plugin.generate_image(settings, device_config)`.
3. `assert_image_snapshot(result, plugin_name, case_name)` hashes the rendered PNG
   and compares it against the stored `.sha256` baseline.
4. If the digest matches → test passes.  If not → the test fails with a clear message
   pointing at the baseline file so you can inspect the diff.

## Running the snapshot tests

```bash
# Normal comparison run (included in the full test suite):
SKIP_BROWSER=1 .venv/bin/python -m pytest tests/snapshots/ -v

# Or via the full suite:
SKIP_BROWSER=1 .venv/bin/python -m pytest tests/ --no-header --tb=no 2>&1 | tail -1
```

## Updating baselines (intentional changes)

When a plugin's output changes *intentionally* (template tweak, font bump, etc.) you must
regenerate the stored baselines.  Use the interactive helper script:

```bash
python scripts/update_snapshots.py
```

Or, to skip the confirmation prompt (e.g. in a CI pipeline where regeneration is wanted):

```bash
python scripts/update_snapshots.py --yes
```

You can also set the env-var directly for a targeted run:

```bash
SNAPSHOT_UPDATE=1 pytest tests/snapshots/ -v
```

After updating, commit both the new `.png` and `.sha256` files together.

## Adding snapshots for a new plugin

1. Write a test in `tests/snapshots/test_plugin_snapshots.py` (or a new file in
   this directory) that:
   - Freezes time / mocks network calls so the output is deterministic.
   - Calls `assert_image_snapshot(result, "<plugin_name>", "<case_name>")`.
2. Run `python scripts/update_snapshots.py` to capture the initial baseline.
3. Commit the `.png` + `.sha256` files alongside the test.

## Design decisions

- **Hash-based comparison** — we compare SHA-256 digests rather than pixel-diffing.
  This keeps the helper dependency-free and fast.  If you need pixel-level diff
  images for CI review, that's a Phase 2 enhancement (see JTN-509 follow-ups).
- **No `pytest-snapshot` dep** — a tiny custom helper avoids adding a new package
  to the lockfile and keeps the comparison logic transparent.
- **PNG binaries** — `.gitattributes` marks `tests/snapshots/**/*.png` as binary so
  git doesn't try to diff them as text.
