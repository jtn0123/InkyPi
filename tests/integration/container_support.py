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
