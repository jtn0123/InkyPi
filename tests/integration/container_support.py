"""Shared plumbing for the ``container`` tests that boot systemd in Docker.

Locally these tests skip when Docker is missing or cannot boot systemd, so a
laptop without Docker still runs the rest of the suite. CI sets
``REQUIRE_INSTALL_CRASH_LOOP_TEST=1`` and then every one of those cases fails
instead: a regression gate that skips looks exactly like one that passed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
import time
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import NoReturn

import pytest

REQUIRED = os.getenv("REQUIRE_INSTALL_CRASH_LOOP_TEST", "").lower() in ("1", "true")


def docker_available() -> bool:
    """Return True if a usable Docker daemon is reachable."""
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(
            ["docker", "info"], capture_output=True, timeout=30, check=False
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return result.returncode == 0


def skip_unless_docker() -> pytest.MarkDecorator:
    """Module mark: skip without Docker, unless CI requires the gate to run."""
    return pytest.mark.skipif(
        not REQUIRED and not docker_available(),
        reason=(
            "requires a running Docker daemon. "
            "Set REQUIRE_INSTALL_CRASH_LOOP_TEST=1 to run anyway (and fail without it)."
        ),
    )


def infrastructure_failed(reason: str) -> NoReturn:
    """Skip when Docker can't do its part; fail if CI requires the gate."""
    if REQUIRED:
        pytest.fail(
            f"{reason}\n(REQUIRE_INSTALL_CRASH_LOOP_TEST is set, so this fails "
            "instead of skipping)",
            pytrace=False,
        )
    pytest.skip(reason)


def cgroup_run_args() -> list[str]:
    """Docker flags that let systemd boot as PID 1, per cgroup version.

    The two hierarchies need opposite things, and getting it wrong does not
    produce a useful error — systemd exits 255 with no logs at all:

    * **cgroup v1** wants the host hierarchy bind-mounted in at
      ``/sys/fs/cgroup`` so systemd can create its own subtree.
    * **cgroup v2** has a single unified hierarchy that a container cannot be
      handed a writable copy of. systemd needs its *own namespaced* view, which
      is what ``--cgroupns=host`` grants; adding the v1 bind-mount on top
      actively breaks it.

    This mattered in practice: the v1 recipe was hardcoded, so on any cgroup v2
    host — which is every current Docker Desktop, colima and modern Linux
    distribution — the container died instantly and the test skipped with
    "systemd did not reach a running state". A skipped regression gate looks
    exactly like a passing one in CI output.

    Falls back to the v2 arrangement when the version cannot be determined,
    since v2 is the default everywhere current.
    """
    probe = subprocess.run(
        ["docker", "info", "--format", "{{.CgroupVersion}}"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    version = (probe.stdout or "").strip()
    if version == "1":
        return ["-v", "/sys/fs/cgroup:/sys/fs/cgroup:rw"]
    return ["--cgroupns=host"]


#: A Debian image whose PID 1 is systemd. The stock enabled-unit links are
#: removed, so the only services that start are the ones a test installs. No
#: build context is sent: nothing is copied in, the tests mount what they need.
SYSTEMD_DOCKERFILE = textwrap.dedent("""
    FROM debian:trixie-slim
    ENV DEBIAN_FRONTEND=noninteractive
    RUN apt-get update \\
        && apt-get install -y --no-install-recommends \\
            systemd systemd-sysv dbus procps \\
        && rm -rf /var/lib/apt/lists/* \\
        && find /etc/systemd/system \\
            /lib/systemd/system/multi-user.target.wants \\
            /lib/systemd/system/local-fs.target.wants \\
            /lib/systemd/system/sockets.target.wants \\
            /lib/systemd/system/basic.target.wants \\
            -type l -delete 2>/dev/null || true
    STOPSIGNAL SIGRTMIN+3
    CMD ["/lib/systemd/systemd"]
    """).strip()


def _docker_quietly(*args: str) -> str:
    """Run a best-effort docker command and return its stdout.

    Never raises. It runs from ``finally`` blocks and failure paths, where an
    exception would replace the error the test is about to report.
    """
    try:
        result = subprocess.run(
            ["docker", *args], capture_output=True, text=True, timeout=60, check=False
        )
    except (subprocess.TimeoutExpired, OSError):
        return ""
    return result.stdout or ""


@contextmanager
def build_systemd_image(prefix: str, *, build_timeout: int) -> Iterator[str]:
    """Build :data:`SYSTEMD_DOCKERFILE` under a unique tag, and remove it after."""
    tag = f"{prefix}-{uuid.uuid4().hex[:8]}"
    try:
        try:
            build = subprocess.run(
                ["docker", "build", "-t", tag, "-"],
                input=SYSTEMD_DOCKERFILE,
                capture_output=True,
                text=True,
                timeout=build_timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            infrastructure_failed(
                f"docker build of the systemd image took over {build_timeout}s"
            )
        if build.returncode != 0:
            infrastructure_failed(
                f"could not build the systemd image (exit {build.returncode}): "
                f"{build.stderr[-400:]}"
            )
        yield tag
    finally:
        _docker_quietly("rmi", "-f", tag)


@contextmanager
def systemd_container(
    image: str,
    prefix: str,
    run_args: Sequence[str] = (),
    *,
    launch_timeout: int = 120,
    boot_timeout: float = 180,
) -> Iterator[str]:
    """Boot *image* with systemd as PID 1 and yield the container's name.

    The container is force-removed on the way out whatever happened, and that
    includes the launch itself. A ``docker run`` that times out on the client
    can still create the container on the daemon. The tests used to start
    their cleanup only after a successful launch, so that case left a
    privileged systemd container running after the test had finished.
    """
    name = f"{prefix}-{uuid.uuid4().hex[:8]}"
    try:
        try:
            start = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--detach",
                    "--name",
                    name,
                    "--privileged",
                    "--tmpfs",
                    "/run",
                    "--tmpfs",
                    "/run/lock",
                    *cgroup_run_args(),
                    *run_args,
                    image,
                ],
                capture_output=True,
                text=True,
                timeout=launch_timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            infrastructure_failed(f"docker run did not return within {launch_timeout}s")
        if start.returncode != 0:
            infrastructure_failed(
                "could not launch the systemd container "
                f"(exit {start.returncode}): {start.stderr[-400:]}"
            )
        _wait_for_boot(name, boot_timeout)
        yield name
    finally:
        _docker_quietly("rm", "-f", name)


def _wait_for_boot(name: str, timeout: float) -> None:
    """Return once systemd in container *name* has finished booting.

    ``systemctl is-system-running --wait`` answers at once, empty and
    non-zero, when it is asked before dbus is up, so one call proves nothing.
    The tests used to retry a fixed 30 times back to back, which made the
    real budget however long 30 ``docker exec`` calls happen to take. This
    waits against a deadline instead, a second apart.
    """
    deadline = time.monotonic() + timeout
    answer = ""
    while time.monotonic() < deadline:
        try:
            probe = subprocess.run(
                ["docker", "exec", name, "systemctl", "is-system-running", "--wait"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except subprocess.TimeoutExpired:
            answer = "(no answer within 30s)"
            continue
        answer = ((probe.stdout or "") + (probe.stderr or "")).strip()
        if (probe.stdout or "").strip() in {"running", "degraded"}:
            return
        time.sleep(1)
    journal = _docker_quietly("exec", name, "journalctl", "-n", "30", "--no-pager")
    infrastructure_failed(
        f"systemd did not finish booting within {timeout:.0f}s; "
        f"last answer: {answer[-400:]!r}\n{journal[-600:]}"
    )
