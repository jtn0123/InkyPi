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


def _make_repo(root: Path, *, v2_has_version: bool = True) -> None:
    """Two tags; HEAD left at v0.0.1. The stub update.sh drops a marker so a
    test can tell whether do_update.sh got as far as delegating."""
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
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "v0.0.2")
    _git(root, "tag", "v0.0.2")
    _git(root, "remote", "add", "origin", str(root))
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
    env.update(
        {
            "INKYPI_LOCKFILE_DIR": str(device["state"]),
            "PROJECT_DIR": str(device["proj"]),
            "INKYPI_VENV_PYTHON": sys.executable,
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
