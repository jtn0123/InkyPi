# Contributing to InkyPi

Thanks for your interest in contributing to InkyPi! This guide covers setup, testing, and the PR process.

## Prerequisites

- Python 3.11-3.13
- A virtual environment (`.venv`)

## Dev Setup

```bash
# Clone the current repo or your fork
git clone https://github.com/jtn0123/InkyPi.git
cd InkyPi

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dev dependencies
pip install -r install/requirements-dev.txt

# Install pre-commit hooks
pre-commit install
```

## Running the Dev Server

```bash
.venv/bin/python src/inkypi.py --dev --web-only
```

This starts the web UI on port 8080 without requiring e-ink display hardware.

## Running Tests

```bash
# Fast iteration — skip browser/Playwright tests (headless Chromium not required)
scripts/test.sh

# Run a specific test file
scripts/test.sh tests/unit/test_inkypi.py -v

# Run with coverage
SKIP_BROWSER=1 .venv/bin/python -m pytest tests/ --cov=src --cov-report=term-missing
```

### Running Browser Tests Locally

Browser tests use Playwright with a headless Chromium instance. There are two groups:

- **UI tests** — 15+ end-to-end Playwright tests covering form workflows, modal lifecycle,
  theme toggle, playlist CRUD, and cross-page navigation.
- **A11y tests** — accessibility audits using axe-core via Playwright.

**First-time setup — install Playwright Chromium:**

```bash
.venv/bin/python -m playwright install chromium
```

**Run all tests including browser tests:**

```bash
SKIP_BROWSER=0 .venv/bin/python -m pytest tests/
# Or simply omit SKIP_BROWSER — it defaults to unset (tests run); Chromium must
# be installed or browser tests will fail (they are not auto-skipped on missing Chromium):
.venv/bin/python -m pytest tests/
```

**Run the lightweight browser smoke gate used by the frontend pre-commit hook:**

```bash
scripts/test.sh browser-smoke
```

**Fine-grained control:**

```bash
# Skip only a11y tests, keep UI tests
SKIP_A11Y=1 .venv/bin/python -m pytest tests/

# Skip only UI tests, keep a11y tests
SKIP_UI=1 .venv/bin/python -m pytest tests/
```

#### Why does SKIP_BROWSER exist?

`SKIP_BROWSER=1` exists for two legitimate use-cases:

1. **Headless CI environments** that do not have Chromium installed (e.g., minimal Docker
   images used in some CI pipelines).
2. **Fast local iteration** — skipping Playwright speeds up the feedback loop when you are
   working on backend logic unrelated to the frontend.

**`SKIP_BROWSER=1` is NOT acceptable when submitting a PR** that touches any of:

- `src/static/**` (CSS, JS, images)
- `src/templates/**` (Jinja2 HTML templates)
- `tests/integration/test_browser_smoke.py` or any other Playwright test file

For any PR touching frontend files, you **must** run:

```bash
SKIP_BROWSER=0 .venv/bin/python -m pytest tests/
```

and confirm all browser tests pass before requesting review.

See `tests/conftest.py` — specifically the `pytest_ignore_collect` hook and the
`UI_BROWSER_TESTS` / `A11Y_BROWSER_TESTS` sets — for the exact logic that governs
which test files are skipped under each env-var combination.

## CSS Build

CSS partials live in `src/static/styles/partials/` and are compiled into the main stylesheet:

```bash
python3 scripts/build_css.py
```

Run this after modifying any CSS partial.

## Commit Convention

We use [Conventional Commits](https://www.conventionalcommits.org/) — and
because PRs are **squash-merged**, **the PR title becomes the commit subject
on `main`** and is what `python-semantic-release` parses to decide the next
version. A PR title that doesn't match a recognized type will silently skip
the release bump. The PR Title Lint check enforces this pre-merge.

Recognized types:

- `feat:` — new feature (→ minor bump)
- `fix:` — bug fix (→ patch bump)
- `perf:` — performance improvement (→ patch bump)
- `refactor:` — code change that neither fixes a bug nor adds a feature
- `docs:` — documentation only
- `style:` — formatting, missing semicolons, etc.
- `test:` — adding or updating tests
- `build:` — build system / dependencies
- `ci:` — CI configuration
- `chore:` — maintenance
- `revert:` — reverts a previous commit

Only `feat`, `fix`, and `perf` trigger a release. A major bump is triggered
either by a `BREAKING CHANGE:` footer in the commit body OR by appending `!`
to the type (e.g. `feat!: drop Python 3.10 support`). The other types are
accepted but don't bump the version. Avoid ad-hoc prefixes like `security:`,
`ui:`, or `css:` — they pass no-lint locally but produce non-releasing merges.

## Code Style

Private helpers (`_*` functions) longer than ~5 lines or with non-obvious intent should have a docstring.

## PR Process

1. Fork the repository
2. Create a feature branch from `main`
3. Write tests for new functionality
4. Ensure all tests pass:
   - Backend-only changes: `scripts/test.sh`
   - **Frontend changes** (`src/static/**`, `src/templates/**`): `scripts/test.sh browser-smoke`
5. Run lint: `scripts/lint.sh`
6. Open a PR against `main`

### PR Checklist

Before marking your PR ready for review, confirm:

- [ ] `scripts/test.sh` passes locally
- [ ] `scripts/lint.sh` passes (ruff + black are CI blockers)
- [ ] **If touching `src/static/**` or `src/templates/**`**: ran `scripts/test.sh browser-smoke` and it passed

## Dependency Management

Dependencies are managed via pip-tools lockfiles with cryptographic hashes. Edit
`install/requirements.in` (runtime) or `install/requirements-dev.in` (dev), then
regenerate the corresponding `.txt` lockfile:

```bash
pip-compile --generate-hashes --no-strip-extras --allow-unsafe \
    install/requirements.in -o install/requirements.txt
```

Always commit both the `.in` source file and the regenerated `.txt` together. See
[docs/dependencies.md](docs/dependencies.md) for full details including CVE
upgrades and cross-platform notes.

## Plugin Development

See [docs/building_plugins.md](docs/building_plugins.md) for a guide on creating new plugins.
