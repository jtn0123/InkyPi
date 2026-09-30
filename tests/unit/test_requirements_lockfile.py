"""
Tests that install/requirements.txt and install/requirements-dev.txt are valid
hash-pinned lockfiles. This prevents regressions where someone
accidentally replaces a hashed lockfile with a bare requirements file.

Related: JTN-516 (Grade F1 — supply-chain integrity)
"""

import re
from importlib.metadata import requires
from pathlib import Path

import pytest
from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

INSTALL_DIR = Path(__file__).parent.parent.parent / "install"
REQUIREMENTS_TXT = INSTALL_DIR / "requirements.txt"
REQUIREMENTS_DEV_TXT = INSTALL_DIR / "requirements-dev.txt"

# Lines that begin a pinned package block (package==version \\)
_PIN_LINE_RE = re.compile(r"^\S+==\S+")
# Hash lines produced by uv --generate-hashes
_HASH_LINE_RE = re.compile(r"--hash=sha256:[0-9a-f]{64}")


def _parse_lockfile(path: Path) -> dict[str, list[str]]:
    """Return {package_pin: [hashes]} for every pinned entry in the lockfile."""
    packages: dict[str, list[str]] = {}
    current_pkg: str | None = None
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        # Skip comments and empty lines
        if not line or line.startswith("#"):
            current_pkg = None
            # A bare package line ends when we hit a blank/comment, but the
            # next pinned line starts a new block — handled below.
            continue
        if _PIN_LINE_RE.match(line):
            # Strip trailing backslash if present
            pkg = line.rstrip(" \\")
            current_pkg = pkg
            packages[current_pkg] = []
        elif _HASH_LINE_RE.search(line) and current_pkg is not None:
            m = _HASH_LINE_RE.search(line)
            if m:
                packages[current_pkg].append(m.group(0))
    return packages


def _active_pins(path: Path, environment: dict[str, str]) -> dict[str, Requirement]:
    pins: dict[str, Requirement] = {}
    for line in path.read_text().splitlines():
        if not _PIN_LINE_RE.match(line):
            continue
        requirement = Requirement(line.rstrip(" \\"))
        if requirement.marker is None or requirement.marker.evaluate(environment):
            pins[canonicalize_name(requirement.name)] = requirement
    return pins


@pytest.mark.parametrize("python_version", ["3.11", "3.12", "3.13"])
@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_universal_dev_lock_is_compatible(python_version: str, platform: str) -> None:
    environment = {key: str(value) for key, value in default_environment().items()}
    environment.update(
        python_version=python_version,
        python_full_version=python_version + ".0",
        sys_platform=platform,
    )
    runtime = _active_pins(REQUIREMENTS_TXT, environment)
    dev = _active_pins(REQUIREMENTS_DEV_TXT, environment)
    for name in runtime.keys() & dev.keys():
        assert runtime[name].specifier == dev[name].specifier, name

    # libcst (used by mutmut 3) selects a separate YAML distribution on 3.13.
    # A lock compiled only on 3.11 misses it and fails hash-checked installation.
    for dependency in requires("libcst") or []:
        requirement = Requirement(dependency)
        if requirement.marker is not None and not requirement.marker.evaluate(
            environment
        ):
            continue
        name = canonicalize_name(requirement.name)
        assert (
            name in dev
        ), f"{dependency} missing for Python {python_version} on {platform}"
        version = next(iter(dev[name].specifier)).version
        assert requirement.specifier.contains(version), dependency


class TestRequirementsLockfile:
    """Verify that both lockfiles contain hash annotations."""

    def test_requirements_txt_exists(self) -> None:
        assert REQUIREMENTS_TXT.exists(), (
            f"{REQUIREMENTS_TXT} does not exist. "
            "Run: uv lock && uv export --format requirements.txt --no-dev --no-emit-project --output-file install/requirements.txt"
        )

    def test_requirements_dev_txt_exists(self) -> None:
        assert REQUIREMENTS_DEV_TXT.exists(), (
            f"{REQUIREMENTS_DEV_TXT} does not exist. "
            "Regenerate the universal dev requirements with uv pip compile --universal."
        )

    def test_requirements_txt_has_hashes(self) -> None:
        """Every pinned package in requirements.txt must have at least one hash."""
        packages = _parse_lockfile(REQUIREMENTS_TXT)
        assert packages, f"{REQUIREMENTS_TXT} contains no pinned packages."
        missing = [pkg for pkg, hashes in packages.items() if not hashes]
        assert not missing, (
            f"The following packages in {REQUIREMENTS_TXT} have no --hash=sha256: entries:\n"
            + "\n".join(f"  {p}" for p in missing)
            + "\nRegenerate with: Run: uv lock && uv export --format requirements.txt --no-dev --no-emit-project --output-file install/requirements.txt"
        )

    def test_requirements_dev_txt_has_hashes(self) -> None:
        """Every pinned package in requirements-dev.txt must have at least one hash."""
        packages = _parse_lockfile(REQUIREMENTS_DEV_TXT)
        assert packages, f"{REQUIREMENTS_DEV_TXT} contains no pinned packages."
        missing = [pkg for pkg, hashes in packages.items() if not hashes]
        assert not missing, (
            f"The following packages in {REQUIREMENTS_DEV_TXT} have no --hash=sha256: entries:\n"
            + "\n".join(f"  {p}" for p in missing)
            + "\nRegenerate with: uv pip compile --universal --python-version 3.11 --generate-hashes install/requirements-dev.in -o install/requirements-dev.txt"
        )

    def test_requirements_txt_hash_count(self) -> None:
        """Sanity check: there should be many hashes (not a trivially empty file)."""
        content = REQUIREMENTS_TXT.read_text()
        count = content.count("--hash=sha256:")
        assert count > 10, (
            f"Expected >10 hash entries in {REQUIREMENTS_TXT}, found {count}. "
            "The file may not be a hashed requirements file."
        )

    def test_requirements_dev_txt_hash_count(self) -> None:
        """Sanity check: dev lockfile should have many more hashes than prod."""
        content = REQUIREMENTS_DEV_TXT.read_text()
        count = content.count("--hash=sha256:")
        assert count > 10, (
            f"Expected >10 hash entries in {REQUIREMENTS_DEV_TXT}, found {count}. "
            "The file may not be a hashed requirements file."
        )

    def test_types_requests_pin_preserved(self) -> None:
        """Requests stubs must match the explicitly validated source pin."""
        content = REQUIREMENTS_DEV_TXT.read_text()
        source = (INSTALL_DIR / "requirements-dev.in").read_text()
        pin = next(
            line for line in source.splitlines() if line.startswith("types-requests==")
        )
        assert pin in content, f"{pin} is missing from requirements-dev.txt"

    def test_requirements_in_exists(self) -> None:
        """Source .in files must be committed alongside lockfiles."""
        assert (INSTALL_DIR / "requirements.in").exists(), (
            "install/requirements.in is missing. "
            "This is the human-maintained constraints reference."
        )

    def test_requirements_dev_in_exists(self) -> None:
        """Dev source .in file must be committed alongside the dev lockfile."""
        assert (INSTALL_DIR / "requirements-dev.in").exists(), (
            "install/requirements-dev.in is missing. "
            "This is the human-maintained constraints reference."
        )
