"""B4: the updater's pre-flight gates abort before anything changes.

Drives the real ``install/do_update.sh`` against a throwaway git repo and the
real ``install/update.sh`` from a throwaway install tree, and asserts that a
failed gate:

* exits non-zero before ``git checkout`` (do_update.sh) or before the service
  is stopped (update.sh),
* leaves HEAD, the ``prev_version`` breadcrumb and the service untouched,
* records ``preflight: <reason>`` as ``last_command`` in
  ``.last-update-failure`` so the settings UI shows why.

The gate logic itself is unit-tested in tests/unit/test_update_preflight.py.
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
INSTALL_DIR = REPO_ROOT / "install"
DO_UPDATE_SH = INSTALL_DIR / "do_update.sh"

HUGE_MB = str(10**12)


def _require_bash_git() -> None:
    if not shutil.which("bash"):
        pytest.skip("bash not available")
    if not shutil.which("git"):
        pytest.skip("git not available")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


EXPECTED_ORIGIN = "https://github.com/jtn0123/InkyPi.git"


def _make_repo(
    root: Path,
    *,
    v2_has_version: bool = True,
    v2_python_floor: str | None = None,
    origin: str | None = EXPECTED_ORIGIN,
) -> None:
    """Two tags; HEAD left at v0.0.1. The stub update.sh drops a marker so a
    test can tell whether do_update.sh got as far as delegating.

    *v2_python_floor* gives v0.0.2 a pyproject.toml with that
    ``requires-python`` floor. *origin* is the configured origin URL (None:
    no origin); a url rewrite makes fetches from it read this repo, offline."""
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(root)], check=True, capture_output=True
    )
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    (root / "src").mkdir()
    (root / "src" / "placeholder.txt").write_text("v1\n")
    (root / "VERSION").write_text("0.0.1\n")
    (root / "install").mkdir()
    (root / "install" / "update.sh").write_text(
        '#!/bin/bash\ntouch "$INKYPI_LOCKFILE_DIR/stub-update-ran"\nexit 0\n'
    )
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "v0.0.1")
    _git(root, "tag", "v0.0.1")
    (root / "src" / "placeholder.txt").write_text("v2\n")
    if v2_has_version:
        (root / "VERSION").write_text("0.0.2\n")
    else:
        (root / "VERSION").unlink()
    if v2_python_floor is not None:
        (root / "pyproject.toml").write_text(
            f'[project]\nname = "inkypi"\nrequires-python = ">={v2_python_floor}"\n'
        )
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "v0.0.2")
    _git(root, "tag", "v0.0.2")
    if origin is not None:
        _git(root, "remote", "add", "origin", origin)
        _git(root, "config", f"url.{root}.insteadOf", origin)
    _git(root, "checkout", "-q", "refs/tags/v0.0.1", "--")


def _install_validator(repo: Path) -> None:
    """Untracked copy of the app's config validator + schema, as on a device."""
    (repo / "src" / "utils").mkdir()
    for rel in ("utils/__init__.py", "utils/config_schema.py"):
        shutil.copy(REPO_ROOT / "src" / rel, repo / "src" / rel)
    (repo / "src" / "config" / "schemas").mkdir(parents=True)
    shutil.copy(
        REPO_ROOT / "src" / "config" / "schemas" / "device_config.schema.json",
        repo / "src" / "config" / "schemas" / "device_config.schema.json",
    )


@pytest.fixture
def device(tmp_path: Path) -> dict[str, Path]:
    _require_bash_git()
    repo = tmp_path / "repo"
    proj = tmp_path / "proj"
    state = tmp_path / "state"
    proj.mkdir()
    state.mkdir()
    (proj / "src").symlink_to(repo / "src", target_is_directory=True)
    # A breadcrumb from the last *real* update; an aborted run must not touch it.
    (state / "prev_version").write_text("v0.0.0\n")
    return {"repo": repo, "proj": proj, "state": state}


def _do_update(
    device: dict[str, Path], target: str, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.pop("INKYPI_UPDATE_MIN_FREE_MB", None)
    env.pop("INKYPI_CONFIG_FILE", None)
    env.pop("INKYPI_GITHUB_REPO", None)
    env.update(
        {
            "INKYPI_LOCKFILE_DIR": str(device["state"]),
            "PROJECT_DIR": str(device["proj"]),
            "INKYPI_VENV_PYTHON": sys.executable,
            # The system-Python gate probes this instead of the host python3.
            "INKYPI_PYTHON_BIN": sys.executable,
            "INKYPI_UPDATE_MIN_FREE_MB": "1",
        }
    )
    env.update(extra_env or {})
    return subprocess.run(
        ["bash", str(DO_UPDATE_SH), target],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _assert_aborted_untouched(
    device: dict[str, Path], proc: subprocess.CompletedProcess[str], needle: str
) -> None:
    combined = proc.stdout + proc.stderr
    assert proc.returncode != 0, combined
    assert "aborted by pre-flight checks" in proc.stderr, combined
    assert _git(device["repo"], "describe", "--tags") == "v0.0.1", combined
    assert (device["repo"] / "src" / "placeholder.txt").read_text() == "v1\n"
    assert (device["state"] / "prev_version").read_text() == "v0.0.0\n"
    assert not (device["state"] / "stub-update-ran").exists()
    record = json.loads((device["state"] / ".last-update-failure").read_text())
    assert record["last_command"].startswith("preflight: "), record
    assert needle in record["last_command"], record
    assert record["exit_code"] != 0


class TestDoUpdatePreflight:
    def test_passing_gates_check_out_and_delegate(
        self, device: dict[str, Path]
    ) -> None:
        _make_repo(device["repo"])
        proc = _do_update(device, "v0.0.2")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "preflight version: ok (version 0.0.2)" in proc.stdout
        assert _git(device["repo"], "describe", "--tags") == "v0.0.2"
        assert (device["state"] / "prev_version").read_text().strip() == "v0.0.1"
        assert (device["state"] / "stub-update-ran").exists()

    def test_target_tag_without_version_aborts_before_checkout(
        self, device: dict[str, Path]
    ) -> None:
        _make_repo(device["repo"], v2_has_version=False)
        proc = _do_update(device, "v0.0.2")
        _assert_aborted_untouched(device, proc, "target VERSION is empty or missing")

    def test_target_needing_newer_python_aborts_before_checkout(
        self, device: dict[str, Path]
    ) -> None:
        """B9: the floor comes from the *target's* pyproject.toml, so a release
        that needs a newer Python is refused while the old code is still on
        disk, not after update.sh has already been switched in."""
        _make_repo(device["repo"], v2_python_floor="99.0")
        proc = _do_update(device, "v0.0.2")
        _assert_aborted_untouched(device, proc, "v0.0.2 needs Python 99.0+")
        assert "requires Python 99.0+" in proc.stderr

    def test_target_within_python_floor_passes(self, device: dict[str, Path]) -> None:
        floor = f"{sys.version_info.major}.{sys.version_info.minor}"
        _make_repo(device["repo"], v2_python_floor=floor)
        proc = _do_update(device, "v0.0.2")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert f"meets the {floor}+ requirement" in proc.stdout
        assert _git(device["repo"], "describe", "--tags") == "v0.0.2"

    def test_old_system_python_aborts_before_checkout(
        self, device: dict[str, Path], tmp_path: Path
    ) -> None:
        """Without a floor in the target, the default (3.13) still applies:
        a Bookworm-era 3.11 keeps its current version and code."""
        fake = tmp_path / "python3.11"
        fake.write_text(
            "#!/bin/sh\n" 'case "$2" in *print*) echo 3.11 ;; *) exit 1 ;; esac\n'
        )
        fake.chmod(0o755)
        _make_repo(device["repo"])
        proc = _do_update(device, "v0.0.2", {"INKYPI_PYTHON_BIN": str(fake)})
        _assert_aborted_untouched(device, proc, "v0.0.2 needs Python 3.13+")
        assert "Trixie" in proc.stderr

    def test_low_disk_aborts_before_checkout(self, device: dict[str, Path]) -> None:
        _make_repo(device["repo"])
        proc = _do_update(device, "v0.0.2", {"INKYPI_UPDATE_MIN_FREE_MB": HUGE_MB})
        _assert_aborted_untouched(device, proc, "MB free")

    def test_invalid_device_config_aborts_before_checkout(
        self, device: dict[str, Path]
    ) -> None:
        _make_repo(device["repo"])
        _install_validator(device["repo"])
        (device["repo"] / "src" / "config" / "device.json").write_text(
            json.dumps({"display_type": "mock", "orientation": "sideways"})
        )
        proc = _do_update(device, "v0.0.2")
        _assert_aborted_untouched(device, proc, "failed schema validation")

    def test_missing_waveshare_driver_aborts_before_checkout(
        self, device: dict[str, Path]
    ) -> None:
        _make_repo(device["repo"])
        _install_validator(device["repo"])
        (device["repo"] / "src" / "config" / "device.json").write_text(
            json.dumps({"display_type": "epd7in3e"})
        )
        proc = _do_update(device, "v0.0.2")
        _assert_aborted_untouched(device, proc, "epd7in3e.py is missing")


class TestDoUpdateOrigin:
    """E10: do_update.sh installs whatever origin serves, as root, so it
    refuses an origin other than the repo the version check reads releases
    from, before fetching anything."""

    @pytest.mark.parametrize(
        "origin",
        [
            "https://github.com/jtn0123/InkyPi.git",
            "https://github.com/jtn0123/InkyPi",
            "https://github.com/jtn0123/InkyPi/",
            "git@github.com:jtn0123/InkyPi.git",
            "git@github.com:jtn0123/InkyPi",
            "ssh://git@github.com/jtn0123/InkyPi.git",
            "https://github.com/JTN0123/inkypi.git",
        ],
    )
    def test_accepts_the_fork_in_https_or_ssh_form(
        self, device: dict[str, Path], origin: str
    ) -> None:
        _make_repo(device["repo"], origin=origin)
        proc = _do_update(device, "v0.0.2")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert _git(device["repo"], "describe", "--tags") == "v0.0.2"

    @pytest.mark.parametrize(
        "origin",
        [
            "https://github.com/fatihak/InkyPi.git",
            "git@github.com:fatihak/InkyPi.git",
            "https://github.com/jtn0123/InkyPi-old.git",
            "https://github.com/jtn0123/InkyPi.git.bak",
            "https://gitlab.com/jtn0123/InkyPi.git",
            "https://example.com/github.com/jtn0123/InkyPi.git",
            None,
        ],
    )
    def test_refuses_any_other_origin_before_fetching(
        self, device: dict[str, Path], origin: str | None
    ) -> None:
        _make_repo(device["repo"], origin=origin)
        proc = _do_update(device, "v0.0.2")
        assert proc.returncode != 0
        assert "Update aborted: origin is" in proc.stderr
        assert "updates come from github.com/jtn0123/InkyPi" in proc.stderr
        assert "Nothing was changed" in proc.stderr
        assert "Fetching latest from origin" not in proc.stdout
        assert not (device["repo"] / ".git" / "FETCH_HEAD").exists()
        assert _git(device["repo"], "describe", "--tags") == "v0.0.1"
        assert (device["state"] / "prev_version").read_text() == "v0.0.0\n"
        assert not (device["state"] / "stub-update-ran").exists()
        record = json.loads((device["state"] / ".last-update-failure").read_text())
        assert record["last_command"] == "verify_origin"

    def test_inkypi_github_repo_lets_a_device_follow_another_fork(
        self, device: dict[str, Path]
    ) -> None:
        """The same override the version check honours
        (services.version_check._GITHUB_REPO)."""
        _make_repo(device["repo"], origin="git@github.com:someone/InkyPi.git")
        proc = _do_update(device, "v0.0.2", {"INKYPI_GITHUB_REPO": "someone/InkyPi"})
        assert proc.returncode == 0, proc.stdout + proc.stderr

        refused = _do_update(device, "v0.0.2")
        assert refused.returncode != 0
        assert "Update aborted: origin is" in refused.stderr

    def test_a_malformed_override_is_refused(self, device: dict[str, Path]) -> None:
        _make_repo(device["repo"])
        proc = _do_update(device, "v0.0.2", {"INKYPI_GITHUB_REPO": "jtn0123 InkyPi"})
        assert proc.returncode != 0
        assert "INKYPI_GITHUB_REPO must look like owner/name" in proc.stderr
        assert _git(device["repo"], "describe", "--tags") == "v0.0.1"


def _add_draft_tag(repo: Path) -> None:
    """Tag v0.0.3 on top of v0.0.2 without moving HEAD: a release that has
    been tagged but not published yet."""
    _git(repo, "checkout", "-q", "refs/tags/v0.0.2", "--")
    (repo / "VERSION").write_text("0.0.3\n")
    _git(repo, "commit", "-q", "-am", "v0.0.3")
    _git(repo, "tag", "v0.0.3")
    _git(repo, "checkout", "-q", "refs/tags/v0.0.1", "--")


def _fake_curl(tmp_path: Path, body: str | None) -> dict[str, str]:
    """A curl that prints *body* (None: fails like an unreachable host) and
    logs its arguments. Returns the env that puts it first on PATH."""
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir()
    log = tmp_path / "curl.log"
    script = f'#!/bin/bash\necho "$*" >> "{log}"\n'
    if body is None:
        script += "exit 22\n"
    else:
        (tmp_path / "curl-body.json").write_text(body)
        script += f'cat "{tmp_path / "curl-body.json"}"\n'
    (bin_dir / "curl").write_text(script)
    (bin_dir / "curl").chmod(0o755)
    return {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}


class TestDoUpdateDefaultTarget:
    """E5: with no tag given, install the latest *published* release. The
    release workflow tags first and publishes only once every file is
    attached, so the newest tag can belong to a draft."""

    def test_installs_the_published_release_not_a_newer_draft_tag(
        self, device: dict[str, Path], tmp_path: Path
    ) -> None:
        _make_repo(device["repo"])
        _add_draft_tag(device["repo"])
        env = _fake_curl(tmp_path, '{"tag_name": "v0.0.2", "draft": false}')
        proc = _do_update(device, "", env)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "Latest release: v0.0.2" in proc.stdout
        assert _git(device["repo"], "describe", "--tags") == "v0.0.2"
        log = (tmp_path / "curl.log").read_text()
        assert "https://api.github.com/repos/jtn0123/InkyPi/releases/latest" in log

    def test_asks_the_fork_the_device_follows(
        self, device: dict[str, Path], tmp_path: Path
    ) -> None:
        _make_repo(device["repo"], origin="https://github.com/someone/InkyPi.git")
        env = _fake_curl(tmp_path, '{"tag_name": "v0.0.2"}')
        proc = _do_update(device, "", {**env, "INKYPI_GITHUB_REPO": "someone/InkyPi"})
        assert proc.returncode == 0, proc.stdout + proc.stderr
        log = (tmp_path / "curl.log").read_text()
        assert "repos/someone/InkyPi/releases/latest" in log

    @pytest.mark.parametrize(
        ("body", "message"),
        [
            (None, "Couldn't ask GitHub for the latest release"),
            ("not json", "Couldn't ask GitHub for the latest release"),
            (
                '{"tag_name": "v0.0.2-rc1"}',
                "Couldn't ask GitHub for the latest release",
            ),
            ('{"tag_name": "v9.9.9"}', "The latest release, v9.9.9, has no tag here"),
        ],
    )
    def test_falls_back_to_the_newest_tag(
        self,
        device: dict[str, Path],
        tmp_path: Path,
        body: str | None,
        message: str,
    ) -> None:
        _make_repo(device["repo"])
        _add_draft_tag(device["repo"])
        proc = _do_update(device, "", _fake_curl(tmp_path, body))
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert message in proc.stdout
        assert "Target version: v0.0.3" in proc.stdout
        assert _git(device["repo"], "describe", "--tags") == "v0.0.3"

    def test_does_not_step_back_from_a_newer_pinned_tag(
        self, device: dict[str, Path], tmp_path: Path
    ) -> None:
        _make_repo(device["repo"])
        _add_draft_tag(device["repo"])
        _git(device["repo"], "checkout", "-q", "refs/tags/v0.0.3", "--")
        proc = _do_update(device, "", _fake_curl(tmp_path, '{"tag_name": "v0.0.2"}'))
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "Already newer than the latest release, v0.0.2" in proc.stdout
        assert _git(device["repo"], "describe", "--tags") == "v0.0.3"

    def test_a_named_tag_skips_the_lookup(
        self, device: dict[str, Path], tmp_path: Path
    ) -> None:
        _make_repo(device["repo"])
        proc = _do_update(device, "v0.0.2", _fake_curl(tmp_path, None))
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert not (tmp_path / "curl.log").exists()


@pytest.fixture
def install_tree(tmp_path: Path) -> dict[str, Path]:
    if not shutil.which("bash"):
        pytest.skip("bash not available")
    project = tmp_path / "inkypi"
    install = project / "install"
    install.mkdir(parents=True)
    for name in ("update.sh", "_common.sh", "_preflight.py"):
        shutil.copy(INSTALL_DIR / name, install / name)
    (project / "VERSION").write_text("2.0.0\n")
    state = tmp_path / "state"
    state.mkdir()
    return {"project": project, "install": install, "state": state}


def _update(
    tree: dict[str, Path], extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.pop("INKYPI_CONFIG_FILE", None)
    env.update(
        {
            "INKYPI_LOCKFILE_DIR": str(tree["state"]),
            "INKYPI_UPDATE_MIN_FREE_MB": "1",
            # Exit 97 at stop_service if the gates pass: proves preflight ran
            # first, without running any real apt/pip/systemctl work.
            "INKYPI_UPDATE_TEST_FAIL_AT": "stop_service",
        }
    )
    env.update(extra_env or {})
    return subprocess.run(
        ["bash", str(tree["install"] / "update.sh")],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _failure(tree: dict[str, Path]) -> dict[str, object]:
    record: dict[str, object] = json.loads(
        (tree["state"] / ".last-update-failure").read_text()
    )
    return record


class TestUpdateShPreflight:
    def test_passing_gates_reach_stop_service(
        self, install_tree: dict[str, Path]
    ) -> None:
        proc = _update(install_tree)
        assert proc.returncode == 97, proc.stdout + proc.stderr
        assert "preflight version: ok (version 2.0.0)" in proc.stdout
        assert _failure(install_tree)["last_command"] == "stop_service"

    def test_empty_version_aborts_before_stop_service(
        self, install_tree: dict[str, Path]
    ) -> None:
        (install_tree["project"] / "VERSION").write_text("\n")
        proc = _update(install_tree)
        assert proc.returncode == 1, proc.stdout + proc.stderr
        record = _failure(install_tree)
        assert str(record["last_command"]).startswith("preflight: ")
        assert "VERSION is empty or missing" in str(record["last_command"])
        assert not (install_tree["state"] / ".install-in-progress").exists()

    def test_low_disk_aborts_before_stop_service(
        self, install_tree: dict[str, Path]
    ) -> None:
        proc = _update(install_tree, {"INKYPI_UPDATE_MIN_FREE_MB": HUGE_MB})
        assert proc.returncode == 1, proc.stdout + proc.stderr
        assert "MB free" in str(_failure(install_tree)["last_command"])
        assert not (install_tree["state"] / ".install-in-progress").exists()
