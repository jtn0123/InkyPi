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
        ``.last-update-failure`` JSON record to $INKYPI_LOCKFILE_DIR."""
        _require_bash_git()
        state_dir = tmp_path / "state"
        state_dir.mkdir()

        # Point PROJECT_DIR at an empty tmpdir so the symlink branch fails.
        # The script also checks $SCRIPT_DIR/../.git — our worktree has a
        # ``.git`` *file* (not directory) there, so the `-d` test also fails
        # and the script correctly falls through to the "cannot determine"
        # error path.
        empty_proj = tmp_path / "empty_proj"
        empty_proj.mkdir()

        proc = _run(
            {
                "INKYPI_LOCKFILE_DIR": str(state_dir),
                "PROJECT_DIR": str(empty_proj),
            }
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


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))
