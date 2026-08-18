"""Auto-rollback driven by real systemd, not by a test calling the script.

``tests/simulation/test_update_rollback_rehearsal.py`` proves ``boot-health.sh``
does the right thing *when invoked*. It cannot prove systemd invokes it — that
depends on ``OnFailure=`` in ``inkypi.service``, ``StartLimitBurst`` being
reached, and the failure unit resolving the script's path on a real filesystem.
Those are systemd's behaviours, so they need a real init.

That gap matters more here than usual: this code only ever runs when the device
is already failing to start, which is the worst moment to discover the wiring
was wrong. A device that updates itself into a non-booting state cannot serve
the UI that offers the rollback button.

The units are installed verbatim. Only timing is overridden via drop-ins, so
the start limit is reached in seconds rather than the production 60 s cadence.
"""

from __future__ import annotations

import shutil
import subprocess
import textwrap
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_DIR = REPO_ROOT / "install"

pytestmark = [
    pytest.mark.container,
    pytest.mark.skipif(
        shutil.which("docker") is None
        or subprocess.run(
            ["docker", "info"], capture_output=True, timeout=30, check=False
        ).returncode
        != 0,
        reason="requires a running Docker daemon",
    ),
]


def _cgroup_run_args() -> list[str]:
    """See test_install_crash_loop._cgroup_run_args — same v1/v2 split."""
    probe = subprocess.run(
        ["docker", "info", "--format", "{{.CgroupVersion}}"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return (
        ["-v", "/sys/fs/cgroup:/sys/fs/cgroup:rw"]
        if (probe.stdout or "").strip() == "1"
        else ["--cgroupns=host"]
    )


@pytest.fixture(scope="module")
def systemd_image() -> Iterator[str]:
    tag = f"inkypi-boot-health-{uuid.uuid4().hex[:8]}"
    dockerfile = textwrap.dedent("""
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
    build = subprocess.run(
        ["docker", "build", "-t", tag, "-f", "-", str(REPO_ROOT)],
        input=dockerfile,
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    if build.returncode != 0:
        pytest.skip(f"could not build systemd image: {build.stderr[-400:]}")
    yield tag
    subprocess.run(["docker", "rmi", "-f", tag], capture_output=True, check=False)


class Container:
    """Thin wrapper so the test body reads as a sequence of shell steps."""

    def __init__(self, name: str) -> None:
        self.name = name

    def exec(self, script: str, timeout: int = 60) -> Any:
        return subprocess.run(
            ["docker", "exec", self.name, "bash", "-lc", script],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    def write(self, path: str, content: str, mode: str = "644") -> None:
        result = self.exec(
            f"mkdir -p $(dirname {path}) && cat > {path} <<'INKYPI_EOF'\n"
            f"{content}\nINKYPI_EOF\nchmod {mode} {path}"
        )
        assert result.returncode == 0, result.stderr


@pytest.fixture
def container(systemd_image: str) -> Iterator[Container]:
    name = f"inkypi-bh-{uuid.uuid4().hex[:8]}"
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
            *_cgroup_run_args(),
            "-v",
            f"{INSTALL_DIR}:/opt/inkypi-install:ro",
            systemd_image,
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if start.returncode != 0:
        pytest.skip(f"could not launch container: {start.stderr[-400:]}")

    ctr = Container(name)
    # `is-system-running --wait` answers empty (and non-zero) if it is asked
    # before dbus is up, so poll rather than trusting a single call.
    state = ""
    for _ in range(30):
        ready = ctr.exec("systemctl is-system-running --wait", timeout=30)
        state = (ready.stdout or "").strip()
        if state in {"running", "degraded"}:
            break
    if state not in {"running", "degraded"}:
        diagnostics = ctr.exec("journalctl -n 30 --no-pager 2>&1 || true").stdout
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)
        pytest.skip(
            f"systemd did not boot inside the container: {state!r}\n{diagnostics[-600:]}"
        )

    try:
        yield ctr
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)


def _install_inkypi(ctr: Container, *, version: str, confirmed: str | None) -> None:
    """Install the real units and scripts, with a deliberately failing app."""
    # The real scripts, copied out of the read-only mount.
    ctr.exec(
        "mkdir -p /usr/local/inkypi/install /var/lib/inkypi "
        "&& cp /opt/inkypi-install/boot-health.sh /usr/local/inkypi/install/ "
        "&& chmod +x /usr/local/inkypi/install/boot-health.sh"
    )
    ctr.write("/usr/local/inkypi/VERSION", version)

    # A rollback stand-in that records that systemd's chain reached it.
    ctr.write(
        "/usr/local/inkypi/install/rollback.sh",
        "#!/bin/bash\n"
        "echo ROLLBACK_TO=$(cat /var/lib/inkypi/prev_version) "
        ">> /var/lib/inkypi/rollback.log\n",
        mode="755",
    )
    ctr.exec("echo '1.0.0' > /var/lib/inkypi/prev_version")
    if confirmed is not None:
        ctr.exec(f"echo '{confirmed}' > /var/lib/inkypi/confirmed_version")

    # The real units, verbatim.
    ctr.exec(
        "cp /opt/inkypi-install/inkypi.service "
        "/opt/inkypi-install/inkypi-failure.service /etc/systemd/system/"
    )

    # An ExecStart that always fails, standing in for a broken build. Timing is
    # compressed so the start limit is hit in seconds; everything else about
    # the unit — including OnFailure= — stays as shipped.
    ctr.write(
        "/etc/systemd/system/inkypi.service.d/test.conf",
        "[Unit]\n"
        "StartLimitIntervalSec=60\n"
        "StartLimitBurst=2\n"
        "[Service]\n"
        "Type=simple\n"
        "ExecStartPre=\n"
        "ExecStart=\n"
        "ExecStart=/bin/bash -c 'exit 1'\n"
        "RestartSec=1\n"
        "WatchdogSec=0\n",
    )
    # The failure unit resolves boot-health.sh through /usr/local/inkypi/src ->
    # repo. There is no repo here, so exercise the direct-install fallback.
    ctr.exec("systemctl daemon-reload")


def _drive_to_start_limit(ctr: Container) -> None:
    """Start the service and let systemd retry until it gives up."""
    ctr.exec("systemctl start inkypi.service", timeout=30)
    ctr.exec(
        "for i in $(seq 1 40); do "
        "  state=$(systemctl show -p ActiveState --value inkypi.service); "
        '  if [ "$state" = "failed" ]; then break; fi; '
        "  sleep 1; "
        "done",
        timeout=90,
    )
    # OnFailure activation is asynchronous; give it a moment to run.
    ctr.exec(
        "for i in $(seq 1 20); do "
        "  if [ -e /var/lib/inkypi/.start-limit-hit ]; then break; fi; "
        "  sleep 1; "
        "done",
        timeout=60,
    )


class TestSystemdActuallyDrivesTheChain:
    def test_onfailure_fires_the_failure_unit(self, container: Any) -> None:
        """The sentinel proves OnFailure= reached inkypi-failure.service."""
        _install_inkypi(container, version="2.0.0", confirmed="1.0.0")
        _drive_to_start_limit(container)

        sentinel = container.exec(
            "test -e /var/lib/inkypi/.start-limit-hit && echo YES"
        )
        assert "YES" in sentinel.stdout, (
            "OnFailure= did not activate inkypi-failure.service; "
            f"journal: {container.exec('journalctl -u inkypi.service -n 20 --no-pager').stdout[-600:]}"
        )

    def test_boot_health_runs_and_counts_the_failure(self, container: Any) -> None:
        """The second ExecStart in the failure unit must actually execute."""
        _install_inkypi(container, version="2.0.0", confirmed="1.0.0")
        _drive_to_start_limit(container)

        counted = container.exec("cat /var/lib/inkypi/failed_starts 2>/dev/null")
        assert counted.stdout.strip().isdigit(), (
            "boot-health.sh did not run under OnFailure; "
            f"failure unit journal: {container.exec('journalctl -u inkypi-failure.service -n 30 --no-pager').stdout[-800:]}"
        )

    def test_repeated_failures_reach_rollback(self, container: Any) -> None:
        """The end-to-end outcome: an unconfirmed version rolls itself back."""
        _install_inkypi(container, version="2.0.0", confirmed="1.0.0")

        # Threshold is 2 start-limit events; each cycle fires the unit once.
        for _ in range(2):
            container.exec("systemctl reset-failed inkypi.service || true")
            _drive_to_start_limit(container)

        log = container.exec("cat /var/lib/inkypi/rollback.log 2>/dev/null")
        assert "ROLLBACK_TO=1.0.0" in log.stdout, (
            "systemd never drove the chain to a rollback; "
            f"state: {container.exec('ls -la /var/lib/inkypi').stdout}"
        )

    def test_a_confirmed_version_is_not_rolled_back(self, container: Any) -> None:
        """A version that worked before points at the environment, not the build."""
        _install_inkypi(container, version="2.0.0", confirmed="2.0.0")

        for _ in range(4):
            container.exec("systemctl reset-failed inkypi.service || true")
            _drive_to_start_limit(container)

        log = container.exec("test -e /var/lib/inkypi/rollback.log && echo EXISTS")
        assert (
            "EXISTS" not in log.stdout
        ), "a previously-confirmed version must never auto-roll-back"


class TestFailureUnitDoesNotMaskTheSentinel:
    def test_a_broken_boot_health_still_leaves_the_sentinel(
        self, container: Any
    ) -> None:
        """The '-' prefix on the ExecStart must keep the sentinel load-bearing."""
        _install_inkypi(container, version="2.0.0", confirmed="1.0.0")
        # Replace boot-health with something that fails outright.
        container.write(
            "/usr/local/inkypi/install/boot-health.sh",
            "#!/bin/bash\nexit 42\n",
            mode="755",
        )
        _drive_to_start_limit(container)

        sentinel = container.exec(
            "test -e /var/lib/inkypi/.start-limit-hit && echo YES"
        )
        assert (
            "YES" in sentinel.stdout
        ), "a failing boot-health.sh masked the start-limit sentinel"
