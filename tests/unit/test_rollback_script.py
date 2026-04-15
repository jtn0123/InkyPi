# pyright: reportMissingImports=false
"""Structural validation of ``install/rollback.sh`` (JTN-708).

These tests deliberately avoid executing the shell script — they verify the
static properties that make the rollback safe (strict mode, semver
validation, delegation to update.sh, state-dir redirection for tests).
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ROLLBACK_SCRIPT = REPO_ROOT / "install" / "rollback.sh"


@pytest.fixture(scope="module")
def rollback_content() -> str:
    return ROLLBACK_SCRIPT.read_text()


def test_rollback_script_exists_and_executable():
    assert ROLLBACK_SCRIPT.is_file(), "install/rollback.sh must exist (JTN-708)"
    mode = ROLLBACK_SCRIPT.stat().st_mode
    assert mode & 0o111, "install/rollback.sh must be executable"


def test_rollback_script_uses_strict_mode(rollback_content):
    """set -euo pipefail is mandatory — any failure must propagate."""
    assert (
        "set -euo pipefail" in rollback_content
    ), "rollback.sh must use 'set -euo pipefail' (JTN-708)"


def test_rollback_script_reads_prev_version(rollback_content):
    """Must read /var/lib/inkypi/prev_version (JTN-673 breadcrumb)."""
    assert "prev_version" in rollback_content
    # Honors INKYPI_LOCKFILE_DIR for test redirection (JTN-704 parity)
    assert (
        "INKYPI_LOCKFILE_DIR" in rollback_content
    ), "rollback.sh must honor INKYPI_LOCKFILE_DIR so tests can redirect"


def test_rollback_script_validates_tag_format(rollback_content):
    """Defense-in-depth semver regex matching the Flask _TAG_RE pattern."""
    # The bash regex must reject arbitrary strings — check the literal pattern
    # is present (kept byte-for-byte aligned with do_update.sh / _TAG_RE).
    assert (
        "^v?[0-9]+\\.[0-9]+\\.[0-9]+(-[A-Za-z0-9.]+)?$" in rollback_content
    ), "rollback.sh must validate prev_version against the strict semver regex"


def test_rollback_script_refuses_missing_breadcrumb(rollback_content):
    """If prev_version file is missing, exit with a distinct code (10)."""
    assert "exit 10" in rollback_content, (
        "rollback.sh must exit 10 when prev_version is missing/empty "
        "so callers can distinguish 'no breadcrumb' from generic errors"
    )


def test_rollback_script_refuses_malformed_breadcrumb(rollback_content):
    """Invalid semver in prev_version must exit distinct from 'missing'."""
    assert (
        "exit 11" in rollback_content
    ), "rollback.sh must exit 11 when prev_version fails semver validation"


def test_rollback_script_checks_out_tag(rollback_content):
    """Must check out refs/tags/<tag> with trailing '--' for safety."""
    assert (
        'git -C "$REPO_DIR" checkout "refs/tags/$PREV_TAG" --' in rollback_content
    ), "rollback.sh must checkout via refs/tags/ to avoid branch-name collisions"


def test_rollback_script_fetches_missing_tag(rollback_content):
    """If the tag isn't present locally, fetch from origin before checkout."""
    assert 'git -C "$REPO_DIR" fetch origin' in rollback_content
    assert "rev-parse --verify" in rollback_content


def test_rollback_script_invokes_update_sh(rollback_content):
    """Rollback delegates to update.sh (JTN-600 / JTN-607 disable-systemd contract)."""
    assert "update.sh" in rollback_content
    # exec'd so the EXIT trap in update.sh (JTN-704) takes over and records
    # any failure to .last-update-failure.
    assert (
        'exec bash "$UPDATE_SCRIPT"' in rollback_content
    ), "rollback.sh must exec update.sh so its EXIT trap handles failure"


def test_rollback_script_does_not_fabricate_random_checkout(rollback_content):
    """Rollback must not fall back to a random tag or branch."""
    # The script should never do a `git checkout main`, `git checkout HEAD~1`,
    # `git tag --sort=-v:refname | head -1`, etc. — if prev_version is absent,
    # we exit hard.
    forbidden_patterns = [
        'git -C "$REPO_DIR" checkout main',
        'git -C "$REPO_DIR" checkout master',
        "tag --sort=-v:refname",
    ]
    for pat in forbidden_patterns:
        assert pat not in rollback_content, (
            f"rollback.sh must not fall back to {pat!r} — missing prev_version "
            "must surface as a hard failure, not a silent alternative checkout"
        )


def test_rollback_script_project_dir_default(rollback_content):
    """PROJECT_DIR defaults to /usr/local/inkypi (mirrors do_update.sh)."""
    assert "/usr/local/inkypi" in rollback_content
