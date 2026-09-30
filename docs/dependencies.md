# Dependency Management

Runtime dependencies are declared in `pyproject.toml`, resolved universally in
`uv.lock`, and exported with hashes to `install/requirements.txt`. Dev and CI
dependencies use `install/requirements-dev.in` and a universal,
hash-pinned `install/requirements-dev.txt`.

## Updating runtime dependencies

Edit `[project.dependencies]` when changing a version range. Keep the legacy
`install/requirements.in` reference and duplicated runtime ranges in
`install/requirements-dev.in` aligned. To update a package within its range:

```bash
uv lock --upgrade-package openai
uv export --format requirements.txt --no-dev --no-emit-project \
    --output-file install/requirements.txt
bash scripts/check_requirements_drift.sh
```

Use `uv lock --upgrade` for a full refresh. Commit the source changes, lock,
and export together. The universal lock covers Linux and macOS, including Pi
architectures; Linux-only dependencies are resolved automatically. Do not
append packages or hashes manually to the generated requirements file.

## Updating dev dependencies

Edit `install/requirements-dev.in`, then resolve universally from Python 3.11,
the oldest supported interpreter. Universal mode preserves Linux-only `memray`
and libcst's Python 3.13-specific YAML backend even when run on a Mac:

```bash
uv --no-config pip compile --universal --python-version 3.11 --fork-strategy fewest \
    --prerelease disallow --upgrade --generate-hashes \
    install/requirements-dev.in -o install/requirements-dev.txt
```

Use `--upgrade-package <name>` instead of `--upgrade` for a targeted refresh.
`--no-config` keeps dev compilation independent of the runtime ARM32 Pi wheel
requirements in `pyproject.toml`: Playwright only supports desktop/64-bit Linux
developer hosts. Runtime resolution retains all Pi targets. uv 0.12.21 is pinned
in the dev input and CI/release compiler steps for consistent resolution.

A platform-specific pip-compile run omits conditional dependencies and must not
replace this universal file. `scripts/check_requirements_drift.sh` re-resolves
against the committed pins to detect missing dependencies without upgrading.
Commit both dev files. Verify that the runtime and dev pins can be installed
together, run `pip check`, and run the test and strict mypy gates.

## Compatibility constraints

- NumPy is capped below 2.5 because 2.5 requires Python 3.12. Runtime and dev
  installs share one version while Python 3.11 is supported.
- `pydantic-core` follows Pydantic's exact pin. Google GenAI currently caps
  `websockets` below 17. Upgrade through their parent libraries.
- Requests type stubs are explicitly pinned to a version validated by mypy.
- Python Semantic Release is pinned in both the dev input and release workflow.
  Its v10 changelog uses update mode and the `<!-- version list -->` marker;
  keep that marker above the existing releases. The parser options preserve
  the previous squash-commit behavior.
- Mutmut 3 uses list-based configuration, named mutant filters, and `mutants/`
  results. See [Mutation Testing](mutation_testing.md).

## CI and pre-commit tools

External GitHub Actions are pinned to full commit hashes, with stable release
versions in comments. Update both together and review upstream migration notes.
Node 24 actions require a current Actions runner: the self-hosted Pi runner
must be at least version 2.327.1 (2.329.0 for authenticated Git in container
actions). GitHub-hosted runners are managed by GitHub.

Pre-commit hook revisions are recorded in `.pre-commit-config.yaml`; keep Ruff
and mypy aligned with the dev lock.

## Hash verification and Pi wheels

`install/install.sh` installs runtime requirements with `--require-hashes`.
Hashes verify downloaded artifacts against the lock; they do not by themselves
establish that an upstream package is trustworthy. Regenerate locks through
the tools above, rather than editing hashes by hand.

Check wheel availability or source-build support before upgrading native
packages on Pi armv7l/armv6l. A local Mac test or a universal resolution does not
prove that a package builds or runs on a physical Pi.

See [Dependency Locking](dependency_locking.md) for the runtime lock design.
