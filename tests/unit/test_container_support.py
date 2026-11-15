"""The container gates skip locally but must fail when CI requires them."""

from __future__ import annotations

import subprocess

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
