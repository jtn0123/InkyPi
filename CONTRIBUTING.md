# Contributing to InkyPi

Thanks for your interest in contributing to InkyPi! This guide covers setup, testing, and the PR process.

## Prerequisites

- Python 3.11+
- A virtual environment (`venv`)

## Dev Setup

```bash
# Clone your fork
git clone https://github.com/<your-username>/InkyPi.git
cd InkyPi

# Create and activate a virtual environment
python -m venv .venv
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
# Run all tests (skip browser/Playwright tests)
SKIP_BROWSER=1 .venv/bin/python -m pytest tests/

# Run a specific test file
.venv/bin/python -m pytest tests/unit/test_inkypi.py -v

# Run with coverage
SKIP_BROWSER=1 .venv/bin/python -m pytest tests/ --cov=src --cov-report=term-missing
```

### Browser Tests

Browser tests require Playwright with Chromium installed:

```bash
playwright install chromium
.venv/bin/python -m pytest tests/  # runs all tests including browser tests
```

Use `SKIP_A11Y=1` or `SKIP_UI=1` to skip accessibility or UI browser tests independently.

## CSS Build

CSS partials live in `src/static/styles/partials/` and are compiled into the main stylesheet:

```bash
python3 scripts/build_css.py
```

Run this after modifying any CSS partial.

## Commit Convention

We use [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` — new feature
- `fix:` — bug fix
- `docs:` — documentation only
- `test:` — adding or updating tests
- `chore:` — maintenance, dependencies, CI

## Code Style

Private helpers (`_*` functions) longer than ~5 lines or with non-obvious intent should have a docstring.

## PR Process

1. Fork the repository
2. Create a feature branch from `main`
3. Write tests for new functionality
4. Ensure all tests pass: `SKIP_BROWSER=1 .venv/bin/python -m pytest tests/`
5. Run pre-commit checks: `pre-commit run --all-files`
6. Open a PR against `main`

## Plugin Development

See [docs/building_plugins.md](docs/building_plugins.md) for a guide on creating new plugins.
