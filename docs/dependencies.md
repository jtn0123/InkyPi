# Dependency Management

Runtime dependencies are declared in `pyproject.toml`, resolved universally in
`uv.lock`, and exported with hashes to `install/requirements.txt`. Dev and CI
tools are the `dev` group under `[dependency-groups]` in the same file, locked
in the same `uv.lock`, and exported (runtime + dev) to
`install/requirements-dev.txt`. Dependabot's `uv` updates cover both.

## Updating runtime dependencies

Edit `[project.dependencies]` when changing a version range. To update a
package within its range:

```bash
uv lock --upgrade-package openai
bash scripts/export_requirements.sh
bash scripts/check_requirements_drift.sh
```

`scripts/export_requirements.sh` writes both exports from `uv.lock` as it
stands (`uv export --frozen`): `install/requirements.txt` without the dev
group and `install/requirements-dev.txt` with it.

Use `uv lock --upgrade` for a full refresh. Commit the source changes, lock,
and export together. The universal lock covers Linux and macOS, including Pi
architectures; Linux-only dependencies are resolved automatically. Do not
append packages or hashes manually to the generated requirements file.

## Updating dev dependencies

Edit the `dev` list under `[dependency-groups]` in `pyproject.toml`, then lock
and export:

```bash
uv lock --upgrade-package ruff
bash scripts/export_requirements.sh
```

The release tools (Python Semantic Release, GitPython's patched floor and
cyclonedx-bom) are a separate `release` group, which `dev` includes. The
release workflow installs only that group, exported from `uv.lock` with hashes,
because its jobs push the release commit and tag and upload release files. In
the same way, memray is in a `memory-diff` group: the per-PR memory report
installs the runtime requirements and that group only, so it measures what the
Pi installs rather than the dev environment.

The lock must satisfy `required-environments`, which includes the 32-bit ARM
Pis. A dev tool with no build for them (Playwright) carries a
`platform_machine` marker so those environments skip it. uv 0.13.4 is pinned in
the dev group and the CI/release steps for consistent resolution.

`scripts/check_requirements_drift.sh` fails when either export no longer
matches `uv.lock`. Commit `pyproject.toml`, `uv.lock` and both exports together,
then run `pip check` and the test and strict mypy gates.

## Dependabot updates

Dependabot's `uv` updates change `pyproject.toml` and `uv.lock` only. The
`Dependabot lock exports` workflow (`.github/workflows/dependabot-exports.yml`)
runs `scripts/export_requirements.sh` on each such PR and pushes the two
exports to its branch. The commit message carries `[dependabot skip]`, so
Dependabot still rebases the PR, and the workflow exports again after each
rebase.

GitHub doesn't start workflows for a push made with the workflow's own token
on its own: the pushed commit's runs wait for approval. Open the PR and click
**Approve workflows to run** so CI, and its required `CI gate (all checks
pass)`, runs on the regenerated files. That click is the only manual step; the
workflow needs no secrets or extra repository settings.

## Installer requirement files

`install.sh` and `update.sh` install three small hashed files as root before
the app's own requirements: `install/bootstrap-requirements.txt` (pip,
setuptools, wheel, packaging), `install/uv-requirements.txt` (uv) and
`install/ws-requirements.txt` (the Waveshare GPIO libraries). Each is compiled
from the `.in` file next to it, which holds the pins. They aren't exported from
`uv.lock`, so Dependabot never updates them. To change one, edit its `.in`
file, then regenerate the `.txt` (shown for `bootstrap`):

```bash
uv --no-config pip compile --universal --python-version 3.13 \
    --prerelease disallow --generate-hashes --no-header --no-annotate \
    install/bootstrap-requirements.in --output-file install/bootstrap-requirements.txt
```

`scripts/check_requirements_drift.sh` fails when a `.txt` doesn't match its
`.in`, when a package also in `uv.lock` (pip, packaging, uv) has a different
version or a hash the lock doesn't list, or when two of the files pin one
package differently (`scripts/check_install_pins.py`). CI's security job runs
pip-audit on all three.

## Compatibility constraints

- `pydantic-core` follows Pydantic's exact pin. Google GenAI currently caps
  `websockets` below 17. Upgrade through their parent libraries.
- Requests type stubs are explicitly pinned to a version validated by mypy.
- Python Semantic Release is pinned in the `release` group; the release
  workflow installs it from the lock.
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

Pre-commit hook revisions are recorded in `.pre-commit-config.yaml`. Ruff,
Black and mypy are local hooks that run from `.venv` (via
`scripts/precommit_tool.sh`), so the dev lock is their only pin.

## Hash verification and Pi wheels

`install/install.sh` installs runtime requirements with `--require-hashes`.
Hashes verify downloaded artifacts against the lock; they do not by themselves
establish that an upstream package is trustworthy. Regenerate locks through
the tools above, rather than editing hashes by hand.

Check wheel availability or source-build support before upgrading native
packages on Pi armv7l/armv6l. A local Mac test or a universal resolution does not
prove that a package builds or runs on a physical Pi.

See [Dependency Locking](dependency_locking.md) for the runtime lock design.
