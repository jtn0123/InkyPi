# pyright: reportMissingImports=false
"""JTN-787: do_update.sh must record failures that happen before delegating
to update.sh (dirty checkout, not-a-repo, etc.).

Before JTN-787, do_update.sh exited non-zero without writing
``.last-update-failure``, so update.sh's JTN-704 trap never ran and the
Settings -> Updates UI surfaced nothing. These tests exercise the new
top-level EXIT trap in do_update.sh and the generated-artifact reset that
prevents a dirty ``src/static/styles/main.css`` from blocking checkout.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DO_UPDATE_SH = REPO_ROOT / "install" / "do_update.sh"


def _require_bash_git() -> None:
    if not shutil.which("bash"):
        pytest.skip("bash not available")
    if not shutil.which("git"):
        pytest.skip("git not available")


def _run(
    env_overrides: dict[str, str],
    cwd: Path | None = None,
    args: list[str] | None = None,
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.update(env_overrides)
    cmd = ["bash", str(DO_UPDATE_SH)]
    if args:
        cmd.extend(args)
    return subprocess.run(
        cmd,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(cwd) if cwd else None,
        check=False,
    )


class TestFailureTrapWritesRecord:
    """do_update.sh's EXIT trap writes ``.last-update-failure`` on abort."""

    def test_aborts_with_failure_file_outside_git_repo(self, tmp_path: Path) -> None:
        """When PROJECT_DIR/src isn't a symlink and SCRIPT_DIR/../.git is
        missing, do_update.sh must exit non-zero AND write a parseable
        ``.last-update-failure`` JSON record to $INKYPI_LOCKFILE_DIR.

        We copy do_update.sh to a fresh tmpdir so its SCRIPT_DIR/../.git
        fallback path cannot resolve to the real repo checkout (on CI the
        runner's workdir IS a git repo, which would otherwise let the
        script proceed past the resolve_repo_dir phase).
        """
        _require_bash_git()
        state_dir = tmp_path / "state"
        state_dir.mkdir()

        # Isolate the script from any ambient git repo so both branches of
        # the repo-resolution logic fail cleanly.
        install_dir = tmp_path / "isolated_install"
        install_dir.mkdir()
        copied_script = install_dir / "do_update.sh"
        copied_script.write_bytes(DO_UPDATE_SH.read_bytes())
        copied_script.chmod(0o755)

        empty_proj = tmp_path / "empty_proj"
        empty_proj.mkdir()

        env = dict(os.environ)
        env.update(
            {
                "INKYPI_LOCKFILE_DIR": str(state_dir),
                "PROJECT_DIR": str(empty_proj),
            }
        )
        proc = subprocess.run(
            ["bash", str(copied_script)],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert proc.returncode != 0, (
            f"do_update.sh must exit non-zero when no repo is found. "
            f"stderr: {proc.stderr!r}"
        )

        failure_file = state_dir / ".last-update-failure"
        assert failure_file.exists(), (
            f"JTN-787: do_update.sh's EXIT trap must write "
            f"{failure_file.name} on non-zero exit. stderr: {proc.stderr!r}"
        )
        parsed = json.loads(failure_file.read_text())
        # Contract shape must match update.sh's JTN-704 trap so downstream
        # readers (read_last_update_failure) don't need to branch on origin.
        for key in ("timestamp", "exit_code", "last_command", "recent_journal_lines"):
            assert key in parsed, f"missing required key {key!r} in {parsed!r}"
        assert parsed["exit_code"] != 0
        # last_command should reflect the phase that was active at failure.
        assert parsed["last_command"] == "resolve_repo_dir", (
            f"expected last_command='resolve_repo_dir' for the no-repo abort "
            f"case; got {parsed['last_command']!r}"
        )


class TestDirtyGeneratedCssDoesNotBlockCheckout:
    """JTN-787: a dirty src/static/styles/main.css must NOT block checkout.

    This simulates the real-world failure mode: the user (or a prior build)
    modified the generated CSS bundle, and ``git checkout <tag>`` refused
    with "Your local changes to the following files would be overwritten by
    checkout". do_update.sh now resets that one known-generated path before
    checkout.
    """

    def _make_repo(self, root: Path) -> None:
        """Build a minimal git repo with two tags, a CSS file, and the
        worktree layout do_update.sh expects (install/ subdir)."""
        subprocess.run(
            ["git", "init", "-q", "-b", "main", str(root)],
            check=True,
            capture_output=True,
        )
        # Configure identity so commits work.
        for k, v in (("user.email", "t@t"), ("user.name", "t")):
            subprocess.run(
                ["git", "-C", str(root), "config", k, v],
                check=True,
                capture_output=True,
            )
        css_dir = root / "src" / "static" / "styles"
        css_dir.mkdir(parents=True)
        css_file = css_dir / "main.css"
        css_file.write_text("/* v1 css */\n")
        # Minimal install/update.sh that exits 0 so the exec at the end of
        # do_update.sh does not explode (we only care about the checkout
        # phase for this test).
        install_dir = root / "install"
        install_dir.mkdir()
        (install_dir / "update.sh").write_text(
            "#!/bin/bash\necho 'stub update.sh'\nexit 0\n"
        )
        (install_dir / "update.sh").chmod(0o755)
        subprocess.run(
            ["git", "-C", str(root), "add", "-A"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(root), "commit", "-q", "-m", "v0.0.1"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(root), "tag", "v0.0.1"],
            check=True,
            capture_output=True,
        )
        # Bump + second tag so TARGET_TAG differs from CURRENT_VERSION.
        css_file.write_text("/* v2 css */\n")
        subprocess.run(
            ["git", "-C", str(root), "add", "-A"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(root), "commit", "-q", "-m", "v0.0.2"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(root), "tag", "v0.0.2"],
            check=True,
            capture_output=True,
        )
        # Arrange a fake "origin" pointing at itself so `git fetch origin`
        # succeeds without hitting the network.
        subprocess.run(
            ["git", "-C", str(root), "remote", "add", "origin", str(root)],
            check=True,
            capture_output=True,
        )

    def test_dirty_main_css_does_not_block_checkout(self, tmp_path: Path) -> None:
        _require_bash_git()
        repo = tmp_path / "repo"
        self._make_repo(repo)
        state_dir = tmp_path / "state"
        state_dir.mkdir()

        # Dirty the generated CSS bundle at HEAD (v0.0.2), then ask
        # do_update.sh to check out v0.0.1. Without the JTN-787 reset, git
        # checkout would abort with "local changes would be overwritten".
        css_file = repo / "src" / "static" / "styles" / "main.css"
        css_file.write_text("/* LOCALLY DIRTIED — should be discarded */\n")
        assert css_file.read_text().startswith("/* LOCALLY DIRTIED")

        # Point PROJECT_DIR at a tmpdir with a `src` symlink into the repo
        # so do_update.sh's realpath-based repo resolution succeeds.
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "src").symlink_to(repo / "src")

        proc = _run(
            {
                "INKYPI_LOCKFILE_DIR": str(state_dir),
                "PROJECT_DIR": str(proj),
            },
            args=["v0.0.1"],
        )
        assert proc.returncode == 0, (
            f"do_update.sh must succeed even with a dirty generated CSS "
            f"bundle (JTN-787). exit={proc.returncode}. stderr: "
            f"{proc.stderr!r}\nstdout: {proc.stdout!r}"
        )
        # After a successful run, HEAD should be at v0.0.1 and the CSS
        # file should hold v0.0.1's content, not the dirty sentinel.
        head_tag = subprocess.run(
            ["git", "-C", str(repo), "describe", "--tags"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert head_tag == "v0.0.1", f"expected HEAD at v0.0.1; got {head_tag!r}"
        assert "LOCALLY DIRTIED" not in css_file.read_text(), (
            "JTN-787 reset should have discarded the dirty main.css before "
            "checkout; dirty content still present"
        )


class TestK2SafeDirectoryAndAutoStash:
    """JTN-K2: do_update.sh must work when run as a different uid than the
    repo owner (dev-install case where the repo lives at /home/$user/InkyPi
    but the update runs as root via systemd-run) AND must not abort on a
    dirty working tree with tracked-file modifications.
    """

    def _make_repo(self, root: Path) -> None:
        """Minimal git repo with two semver tags, an install/ subdir with a
        stub update.sh, and an ``origin`` remote pointing at itself so
        ``git fetch origin`` succeeds offline.
        """
        subprocess.run(
            ["git", "init", "-q", "-b", "main", str(root)],
            check=True,
            capture_output=True,
        )
        for k, v in (("user.email", "t@t"), ("user.name", "t")):
            subprocess.run(
                ["git", "-C", str(root), "config", k, v],
                check=True,
                capture_output=True,
            )
        # Tracked file we can dirty to exercise the auto-stash path.
        (root / "src").mkdir()
        tracked = root / "src" / "placeholder.txt"
        tracked.write_text("v1\n")
        # Also seed the generated-CSS path so the narrow JTN-787 reset
        # still has something to target (keeps the two fixes orthogonal).
        css_dir = root / "src" / "static" / "styles"
        css_dir.mkdir(parents=True)
        (css_dir / "main.css").write_text("/* v1 css */\n")
        # Stub update.sh that exits 0 so do_update.sh's final exec is a no-op.
        install_dir = root / "install"
        install_dir.mkdir()
        (install_dir / "update.sh").write_text(
            "#!/bin/bash\necho 'stub update.sh'\nexit 0\n"
        )
        (install_dir / "update.sh").chmod(0o755)
        subprocess.run(
            ["git", "-C", str(root), "add", "-A"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(root), "commit", "-q", "-m", "v0.0.1"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(root), "tag", "v0.0.1"],
            check=True,
            capture_output=True,
        )
        tracked.write_text("v2\n")
        subprocess.run(
            ["git", "-C", str(root), "add", "-A"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(root), "commit", "-q", "-m", "v0.0.2"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(root), "tag", "v0.0.2"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(root), "remote", "add", "origin", str(root)],
            check=True,
            capture_output=True,
        )

    def test_safe_directory_override_tolerates_dubious_ownership(
        self, tmp_path: Path
    ) -> None:
        """Simulate the dev-install scenario where do_update.sh (running as
        root via systemd-run) operates against a repo owned by another user.
        Prior to K2, ``git rev-parse`` tripped CVE-2022-24765's ownership
        guard and do_update.sh exited with "not a git repository".
        """
        _require_bash_git()

        # Confirm this git build honours the test knob; skip if not.
        probe_repo = tmp_path / "probe"
        probe_repo.mkdir()
        subprocess.run(
            ["git", "init", "-q", str(probe_repo)], check=True, capture_output=True
        )
        probe = subprocess.run(
            ["git", "-C", str(probe_repo), "rev-parse", "--git-dir"],
            env={**os.environ, "GIT_TEST_ASSUME_DIFFERENT_OWNER": "1"},
            capture_output=True,
            text=True,
            check=False,
        )
        if probe.returncode == 0:
            pytest.skip(
                "this git build ignores GIT_TEST_ASSUME_DIFFERENT_OWNER; "
                "cannot simulate CVE-2022-24765 ownership mismatch"
            )
        assert "dubious ownership" in (probe.stderr + probe.stdout).lower()

        repo = tmp_path / "repo"
        self._make_repo(repo)
        state_dir = tmp_path / "state"
        state_dir.mkdir()

        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "src").symlink_to(repo / "src")

        proc = _run(
            {
                "INKYPI_LOCKFILE_DIR": str(state_dir),
                "PROJECT_DIR": str(proj),
                "GIT_TEST_ASSUME_DIFFERENT_OWNER": "1",
            },
            args=["v0.0.1"],
        )
        combined = proc.stdout + proc.stderr
        assert proc.returncode == 0, (
            "JTN-K2 regression: do_update.sh rejected a repo owned by "
            f"another user. rc={proc.returncode}\n{combined}"
        )
        # Neither the masking error nor the raw git warning should leak.
        assert "not a git repository" not in combined, (
            f"ownership guard masked as 'not a git repository': {combined!r}"
        )
        assert "dubious ownership" not in combined, (
            "raw dubious-ownership warning reached the user — wrapper "
            f"is missing the safe.directory override: {combined!r}"
        )

    def test_auto_stash_unblocks_checkout_with_dirty_tracked_file(
        self, tmp_path: Path
    ) -> None:
        """Dev installs sometimes carry uncommitted tracked-file edits.
        Prior to K2, ``git checkout <tag>`` aborted with "Your local
        changes would be overwritten by checkout" and the update failed
        with no clean recovery.  K2 adds an auto-stash before checkout
        that preserves the edit in the stash list for later recovery.
        """
        _require_bash_git()
        repo = tmp_path / "repo"
        self._make_repo(repo)
        state_dir = tmp_path / "state"
        state_dir.mkdir()

        # Pin HEAD at v0.0.1 then dirty a tracked file.  Asking for v0.0.2
        # exercises the checkout path; tracked-file change is not in the
        # narrow JTN-787 allowlist, so only auto-stash can unblock it.
        subprocess.run(
            ["git", "-C", str(repo), "checkout", "-q", "v0.0.1"],
            check=True,
            capture_output=True,
        )
        tracked = repo / "src" / "placeholder.txt"
        tracked.write_text("LOCALLY_DIRTY\n")

        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "src").symlink_to(repo / "src")

        proc = _run(
            {
                "INKYPI_LOCKFILE_DIR": str(state_dir),
                "PROJECT_DIR": str(proj),
            },
            args=["v0.0.2"],
        )
        combined = proc.stdout + proc.stderr
        assert proc.returncode == 0, (
            f"JTN-K2 regression: checkout aborted on dirty tracked file. "
            f"rc={proc.returncode}\n{combined}"
        )
        assert "would be overwritten by checkout" not in combined
        # Stash should hold the rescued edit for later recovery.
        stash_list = subprocess.run(
            ["git", "-C", str(repo), "stash", "list"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert "auto-stash by do_update.sh" in stash_list, (
            "auto-stash entry missing from stash list — user cannot "
            f"recover their edits. stash list: {stash_list!r}"
        )
        # Checkout must actually land on v0.0.2, not silently stay at v0.0.1.
        head_tag = subprocess.run(
            ["git", "-C", str(repo), "describe", "--tags"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert head_tag == "v0.0.2", f"expected HEAD at v0.0.2; got {head_tag!r}"


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))
