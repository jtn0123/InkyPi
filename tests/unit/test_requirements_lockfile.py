"""
Tests that install/requirements.txt and install/requirements-dev.txt are valid
pip-compile hash-pinned lockfiles. This prevents regressions where someone
accidentally replaces a hashed lockfile with a bare requirements file.

Related: JTN-516 (Grade F1 — supply-chain integrity)
"""

import re
from pathlib import Path

INSTALL_DIR = Path(__file__).parent.parent.parent / "install"
REQUIREMENTS_TXT = INSTALL_DIR / "requirements.txt"
REQUIREMENTS_DEV_TXT = INSTALL_DIR / "requirements-dev.txt"

# Lines that begin a pinned package block (package==version \\)
_PIN_LINE_RE = re.compile(r"^\S+==\S+")
# Hash lines produced by pip-compile --generate-hashes
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


class TestRequirementsLockfile:
    """Verify that both lockfiles contain pip-compile-style hash annotations."""

    def test_requirements_txt_exists(self) -> None:
        assert REQUIREMENTS_TXT.exists(), (
            f"{REQUIREMENTS_TXT} does not exist. "
            "Run: pip-compile --generate-hashes install/requirements.in -o install/requirements.txt"
        )

    def test_requirements_dev_txt_exists(self) -> None:
        assert REQUIREMENTS_DEV_TXT.exists(), (
            f"{REQUIREMENTS_DEV_TXT} does not exist. "
            "Run: pip-compile --generate-hashes install/requirements-dev.in -o install/requirements-dev.txt"
        )

    def test_requirements_txt_has_hashes(self) -> None:
        """Every pinned package in requirements.txt must have at least one hash."""
        packages = _parse_lockfile(REQUIREMENTS_TXT)
        assert packages, f"{REQUIREMENTS_TXT} contains no pinned packages."
        missing = [pkg for pkg, hashes in packages.items() if not hashes]
        assert not missing, (
            f"The following packages in {REQUIREMENTS_TXT} have no --hash=sha256: entries:\n"
            + "\n".join(f"  {p}" for p in missing)
            + "\nRegenerate with: pip-compile --generate-hashes install/requirements.in -o install/requirements.txt"
        )

    def test_requirements_dev_txt_has_hashes(self) -> None:
        """Every pinned package in requirements-dev.txt must have at least one hash."""
        packages = _parse_lockfile(REQUIREMENTS_DEV_TXT)
        assert packages, f"{REQUIREMENTS_DEV_TXT} contains no pinned packages."
        missing = [pkg for pkg, hashes in packages.items() if not hashes]
        assert not missing, (
            f"The following packages in {REQUIREMENTS_DEV_TXT} have no --hash=sha256: entries:\n"
            + "\n".join(f"  {p}" for p in missing)
            + "\nRegenerate with: pip-compile --generate-hashes install/requirements-dev.in -o install/requirements-dev.txt"
        )

    def test_requirements_txt_hash_count(self) -> None:
        """Sanity check: there should be many hashes (not a trivially empty file)."""
        content = REQUIREMENTS_TXT.read_text()
        count = content.count("--hash=sha256:")
        assert count > 10, (
            f"Expected >10 hash entries in {REQUIREMENTS_TXT}, found {count}. "
            "The file may not be a pip-compile lockfile."
        )

    def test_requirements_dev_txt_hash_count(self) -> None:
        """Sanity check: dev lockfile should have many more hashes than prod."""
        content = REQUIREMENTS_DEV_TXT.read_text()
        count = content.count("--hash=sha256:")
        assert count > 10, (
            f"Expected >10 hash entries in {REQUIREMENTS_DEV_TXT}, found {count}. "
            "The file may not be a pip-compile lockfile."
        )

    def test_types_requests_pin_preserved(self) -> None:
        """types-requests must stay pinned at 2.32.0.20241016 (PR #301 / JTN-525)."""
        content = REQUIREMENTS_DEV_TXT.read_text()
        assert "types-requests==2.32.0.20241016" in content, (
            "types-requests==2.32.0.20241016 is missing from requirements-dev.txt. "
            "This pin was added in PR #301 (JTN-525) for mypy strict-mode compatibility. "
            "Ensure requirements-dev.in specifies: types-requests==2.32.0.20241016"
        )

    def test_requirements_in_exists(self) -> None:
        """Source .in files must be committed alongside lockfiles."""
        assert (INSTALL_DIR / "requirements.in").exists(), (
            "install/requirements.in is missing. "
            "This is the human-maintained source file for pip-compile."
        )

    def test_requirements_dev_in_exists(self) -> None:
        """Dev source .in file must be committed alongside the dev lockfile."""
        assert (INSTALL_DIR / "requirements-dev.in").exists(), (
            "install/requirements-dev.in is missing. "
            "This is the human-maintained source file for pip-compile."
        )
