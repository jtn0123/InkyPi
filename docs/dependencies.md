# Dependency Management

InkyPi uses a two-layer approach: loose `.in` source files that express intent,
and `pip-compile --generate-hashes` lockfiles that pin every transitive dep with
cryptographic hashes.

## Why hashes matter

Supply-chain attacks on PyPI are real. Typosquatted packages (`colorama` vs
`colourama`), post-release tampering, and compromised mirrors have all been used
to inject malicious code. `pip install --require-hashes` verifies every wheel's
SHA-256 before execution, so a tampered artifact is rejected even if the version
number looks correct.

Example attack surface without hashes:

- `pyyaml` — a popular dep; a mirror serving a backdoored wheel would pass a
  plain `pip install pyyaml==6.0.1` without complaint.
- `requests`, `urllib3` — network libraries; ideal injection vectors.
- Any transitive dep added silently by an upstream package.

## File layout

| File | Purpose |
|------|---------|
| `install/requirements.in` | Human-maintained runtime constraints (`>=X.Y,<X+1`) |
| `install/requirements-dev.in` | Human-maintained dev/CI constraints |
| `install/requirements.txt` | **Generated** lockfile — hashed, exact pins, do not edit by hand |
| `install/requirements-dev.txt` | **Generated** dev lockfile — hashed, exact pins, do not edit by hand |

## How to bump a dependency

1. Edit the relevant `.in` file (e.g. loosen or tighten a bound).
2. Regenerate the lockfile:

   ```bash
   pip-compile --generate-hashes --no-strip-extras --allow-unsafe \
       install/requirements.in -o install/requirements.txt
   ```

   Or for dev deps:

   ```bash
   pip-compile --generate-hashes --no-strip-extras --allow-unsafe \
       install/requirements-dev.in -o install/requirements-dev.txt
   ```

3. Commit **both** the `.in` and the generated `.txt`.

## How to add a new dependency

1. Add it to the appropriate `.in` file with a semver cap (e.g. `newlib>=1.2,<2`).
2. Run pip-compile as above.
3. Commit both files.

## How to upgrade after a CVE

Use `--upgrade-package` to re-resolve only the affected package (and its
transitive deps) without upgrading everything else:

```bash
pip-compile --generate-hashes --no-strip-extras --allow-unsafe \
    --upgrade-package requests \
    install/requirements.in -o install/requirements.txt
```

## `--require-hashes` in install.sh

`install/install.sh` passes `--require-hashes` to pip when installing runtime
deps. This means pip will refuse to install any package whose wheel hash does not
appear in `install/requirements.txt`. If a new package needs to be added, the
lockfile must be regenerated (see above) before the installer will accept it.

## Cross-platform note (Pi Zero 2 W — armv7l)

`pip-compile` is run on a development machine (typically x86_64 or arm64 macOS).
When `--generate-hashes` is used, pip-compile fetches the metadata for **all**
wheels published for each package version on PyPI and records every hash. This
means the resulting lockfile contains hashes for `manylinux_2_17_armv7l` wheels
alongside `macosx_arm64` and `linux_x86_64` wheels.

When pip runs on the Pi with `--require-hashes`, it downloads only the armv7l
wheel (or falls back to the sdist), looks up its hash in the lockfile, and
verifies it — this works correctly because the lockfile already contains that
hash.

If a package publishes no armv7l wheel and no universal sdist, pip will fail at
install time. In that case:

1. Check whether the package builds from source on armv7l.
2. If not, find an alternative package or pin to a version that does publish
   armv7l wheels.
3. Document the constraint in `requirements.in` with an inline comment.

Packages currently guarded with `sys_platform == "linux"` in `requirements.in`
(`inky`, `cysystemd`, `pi-heif`) are Pi-only and do not need to be resolved on
dev machines.
