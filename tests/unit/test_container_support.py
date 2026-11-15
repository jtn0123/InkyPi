"""The container gates skip locally but must fail when CI requires them."""

from __future__ import annotations

import subprocess
import time

import pytest
from tests.integration import container_support


def test_infrastructure_failure_skips_when_not_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(container_support, "REQUIRED", False)
    with pytest.raises(pytest.skip.Exception, match="no docker"):
        container_support.infrastructure_failed("no docker")


def test_infrastructure_failure_fails_when_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(container_support, "REQUIRED", True)
    with pytest.raises(pytest.fail.Exception, match="no docker"):
        container_support.infrastructure_failed("no docker")


@pytest.mark.parametrize(
    ("required", "docker", "skipped"),
    [(False, False, True), (False, True, False), (True, False, False)],
)
def test_docker_mark_only_skips_when_not_required(
    monkeypatch: pytest.MonkeyPatch, required: bool, docker: bool, skipped: bool
) -> None:
    monkeypatch.setattr(container_support, "REQUIRED", required)
    monkeypatch.setattr(container_support, "docker_available", lambda: docker)
    mark = container_support.skip_unless_docker()
    assert mark.args == (skipped,)


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("1\n", ["-v", "/sys/fs/cgroup:/sys/fs/cgroup:rw"]),
        ("2\n", ["--cgroupns=host"]),
        ("", ["--cgroupns=host"]),
    ],
)
def test_cgroup_flags_follow_the_cgroup_version(
    monkeypatch: pytest.MonkeyPatch, version: str, expected: list[str]
) -> None:
    class _Probe:
        stdout = version

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Probe())
    assert container_support.cgroup_run_args() == expected


class _FakeDocker:
    """Stands in for subprocess.run and records every docker call."""

    def __init__(self, *, run: object = "ok", boot: str = "running\n") -> None:
        self.calls: list[list[str]] = []
        self._run = run
        self._boot = boot

    def __call__(
        self, argv: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        verb = argv[1]
        if verb == "run" and isinstance(self._run, BaseException):
            raise self._run
        stdout = ""
        if verb == "info":
            stdout = "2\n"
        elif argv[-2:] == ["is-system-running", "--wait"]:
            stdout = self._boot
        return subprocess.CompletedProcess(argv, 0, stdout, "")

    def removed(self, name: str) -> bool:
        return ["docker", "rm", "-f", name] in self.calls

    def launched_name(self) -> str:
        argv = next(c for c in self.calls if c[1] == "run")
        return argv[argv.index("--name") + 1]


def test_a_launch_that_times_out_still_removes_the_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The daemon can create the container after the client gives up waiting."""
    docker = _FakeDocker(run=subprocess.TimeoutExpired(["docker", "run"], 60))
    monkeypatch.setattr(subprocess, "run", docker)
    monkeypatch.setattr(container_support, "REQUIRED", False)

    with pytest.raises(pytest.skip.Exception, match="did not return within 60s"):
        with container_support.systemd_container("img", "t", launch_timeout=60):
            pytest.fail("the body must not run when the launch failed")

    assert docker.removed(docker.launched_name())


def test_a_failing_test_body_still_removes_the_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    docker = _FakeDocker()
    monkeypatch.setattr(subprocess, "run", docker)

    with pytest.raises(AssertionError):
        with container_support.systemd_container("img", "t") as name:
            assert not docker.removed(name)
            raise AssertionError("scenario failed")

    assert docker.removed(name)


def test_a_container_that_never_boots_is_reported_and_removed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    docker = _FakeDocker(boot="starting\n")
    monkeypatch.setattr(subprocess, "run", docker)
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    monkeypatch.setattr(container_support, "REQUIRED", True)

    with pytest.raises(pytest.fail.Exception, match="did not finish booting"):
        with container_support.systemd_container("img", "t", boot_timeout=0.05):
            pytest.fail("the body must not run before systemd has booted")

    assert docker.removed(docker.launched_name())
