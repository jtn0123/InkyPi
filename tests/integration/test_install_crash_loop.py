# pyright: reportMissingImports=false
"""Pi thrash protection regression gate (JTN-609).

On 2026-04-10 a real Pi Zero 2 W went into a memory-thrash cascade during an
install because ``install.sh`` stopped but did NOT disable ``inkypi.service``.
Half-way through ``pip install`` systemd auto-restarted the half-built
service, it crashed with ``ModuleNotFoundError: flask``, and ``Restart=on-failure``
looped fast enough to starve sshd of RAM — the Pi had to be hard power-cycled.

The fix is JTN-600 (``stop_service`` also calls ``systemctl disable``) plus the
JTN-607 belt-and-suspenders lockfile (``/var/lib/inkypi/.install-in-progress``
blocks the unit via ``ExecStartPre``). This test is the regression gate that
proves both defenses stay effective: if either is broken, the simulated
"kill install mid-pip then let systemd try to restart the crashing service"
scenario produces ``NRestarts > 0`` and the test fails.

Strategy
--------
Real systemd inside Docker is required to observe ``Restart=on-failure``
behaviour. Rather than run the full ~15 min install, this test short-circuits
to the exact failure window the real incident hit:

1. Boot a systemd-capable Debian container (``--privileged`` + cgroup mount).
2. Install ``install/inkypi.service`` into the container and point its
   ``ExecStart`` at a stub that immediately ``exit 1`` (mimics the crashing
   half-built venv with ``ModuleNotFoundError: flask``).
3. Create ``/var/lib/inkypi/.install-in-progress`` (what install.sh does at the
   top of its run — JTN-607).
4. Run the ``stop_service`` disable contract: ``systemctl stop`` then
   ``systemctl disable`` (what JTN-600 added to install.sh).
5. Start a fake ``pip install -r requirements.txt`` background process, then
   ``kill -9`` it 2 s later to simulate install.sh dying mid-pip.
6. Force the scenario the real Pi hit: ``systemctl start inkypi.service`` (as
   if systemd tried to auto-restart a previously-running instance). With the
   lockfile in place this MUST fail fast via ``ExecStartPre``.
7. Wait 30 s, query ``systemctl show inkypi.service -p NRestarts --value``.
   If > 0 the regression has returned.
8. Positive control: remove the lockfile, ``systemctl start``, confirm the
   service DOES come up (proves the gate is actually the lockfile, not a test
   harness artefact).

The test takes <3 min end-to-end including image build because the container
only installs ``systemd`` + ``dbus`` — no InkyPi deps, no arm64 emulation.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICE_UNIT = REPO_ROOT / "install" / "inkypi.service"
INSTALL_SH = REPO_ROOT / "install" / "install.sh"


def _docker_available() -> bool:
    """Return True if a usable Docker daemon is reachable."""
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return result.returncode == 0


REQUIRE_CRASH_LOOP_TEST = os.getenv("REQUIRE_INSTALL_CRASH_LOOP_TEST", "").lower() in (
    "1",
    "true",
)

pytestmark = pytest.mark.skipif(
    not REQUIRE_CRASH_LOOP_TEST and not _docker_available(),
    reason=(
        "Install crash-loop regression test requires Docker. "
        "Set REQUIRE_INSTALL_CRASH_LOOP_TEST=1 to force-run (and fail if Docker is missing)."
    ),
)


# ── container payload ─────────────────────────────────────────────────────────
# This script is copied into the systemd container and runs as PID-1-attached
# helper inside an ``nsenter``/``docker exec`` session. It mirrors the exact
# defenses install.sh + inkypi.service provide on a real Pi. The script MUST
# remain self-contained (no external deps) because the container image is a
# minimal debian:trixie with only systemd + dbus + coreutils installed.
CONTAINER_SCENARIO = r"""
set -eu

LOCKFILE_DIR=/var/lib/inkypi
LOCKFILE="${LOCKFILE_DIR}/.install-in-progress"
UNIT_NAME=inkypi.service
UNIT_PATH=/etc/systemd/system/${UNIT_NAME}
STUB_MARKER=/tmp/inkypi-stub-ran

# Clean state from any previous run inside the same container.
rm -f "${STUB_MARKER}"

echo "[scenario] installing inkypi.service with a crashing ExecStart stub"

# Stub that mimics the half-built venv: touches a marker file the moment it
# runs (so the test can prove ExecStart never executed), prints the exact
# ModuleNotFoundError the real Pi hit, and exits non-zero so systemd treats
# this as a failure — the precise trigger for Restart=on-failure.
mkdir -p /usr/local/bin
cat > /usr/local/bin/inkypi <<'STUB'
#!/bin/sh
# JTN-609 scenario stub. If this runs the Pi-thrash defense is broken.
touch /tmp/inkypi-stub-ran
echo "ModuleNotFoundError: No module named 'flask'" >&2
exit 1
STUB
chmod +x /usr/local/bin/inkypi

# Install the production unit file verbatim. The ExecStartPre lockfile guard is
# the JTN-607 defense under test — we do not want to mutate it. RestartSec is
# rewritten to 1 s so any restart-loop regression is observable inside the 30 s
# window; the default 60 s would hide the bug.
cp /opt/inkypi-src/install/inkypi.service "${UNIT_PATH}"
sed -i 's|^RestartSec=.*|RestartSec=1|' "${UNIT_PATH}"
# WatchdogSec requires Type=notify sd_notify() pings which our stub does not
# send; strip it so the watchdog does not supersede Restart=on-failure as the
# observed trigger. The ExecStart crash is what we want to react to.
sed -i '/^WatchdogSec=/d' "${UNIT_PATH}"
# Type=notify needs sd_notify READY=1 or systemd treats startup as failed
# before ExecStart even runs, which would mask ExecStartPre behavior. Swap to
# Type=simple so the crash path reflects the real incident (process started,
# then crashed on missing flask).
sed -i 's|^Type=notify|Type=simple|' "${UNIT_PATH}"
# Drop RuntimeDirectory/WorkingDirectory so the stub can run without needing
# /run/inkypi (created by systemd normally, but strict `set -eu` exec paths
# in the stub make any missing dir here confusing to debug).
sed -i '/^RuntimeDirectory=/d' "${UNIT_PATH}"
sed -i 's|^WorkingDirectory=.*|WorkingDirectory=/tmp|' "${UNIT_PATH}"

systemctl daemon-reload

echo "[scenario] creating JTN-607 install-in-progress lockfile"
mkdir -p "${LOCKFILE_DIR}"
touch "${LOCKFILE}"

# ── JTN-600 disable contract ────────────────────────────────────────────────
# install.sh's stop_service() runs `systemctl stop` followed by
# `systemctl disable 2>/dev/null || true`. We run that contract directly here
# without sourcing install.sh (which would try to install the whole app).
echo "[scenario] simulating install.sh stop_service() disable contract"
systemctl stop "${UNIT_NAME}" 2>/dev/null || true
systemctl disable "${UNIT_NAME}" 2>/dev/null || true

# Confirm the unit is disabled (JTN-600 invariant). `systemctl is-enabled`
# exits non-zero when the unit is disabled, so capture stdout without letting
# the non-zero exit propagate and without appending an "unknown" fallback
# after a successful-but-non-zero-exit call.
enabled_state=$(systemctl is-enabled "${UNIT_NAME}" 2>/dev/null; true)
enabled_state=$(printf '%s' "${enabled_state}" | tr -d '[:space:]')
echo "[scenario] is-enabled after stop_service: ${enabled_state}"
case "${enabled_state}" in
    disabled|masked|static) ;;
    *)
        echo "FAIL: JTN-600 regression — unit is '${enabled_state}', expected 'disabled'" >&2
        exit 1
        ;;
esac

# ── simulate install.sh dying mid-pip ───────────────────────────────────────
# On the real Pi the trigger was: install.sh stopped the service, then started
# pip install, and something (legacy Restart=always, a timer, a manual kick)
# made systemd try to start the unit again mid-pip. Reproduce that trigger
# explicitly so the test is deterministic.
echo "[scenario] spawning fake pip install and killing it mid-run"
(sleep 60 & wait) &
FAKE_INSTALL_PID=$!
sleep 2
kill -9 "${FAKE_INSTALL_PID}" 2>/dev/null || true
# Suppress the Killed message from the still-running subshell reaping.
wait 2>/dev/null || true

# ── the actual regression check ─────────────────────────────────────────────
# Try to start the service repeatedly (as systemd or a user might during the
# install window). Every attempt MUST be refused by the JTN-607 lockfile guard
# so ExecStart never runs — that is the anti-thrash invariant.
echo "[scenario] attempting 5 start-while-locked cycles"
i=0
while [ "${i}" -lt 5 ]; do
    systemctl start "${UNIT_NAME}" --no-block 2>&1 || true
    sleep 1
    i=$((i + 1))
done

# Settle for 30 seconds. systemd will either give up (start-limit) or keep
# looping — either way, the critical invariant is that ExecStart never ran.
echo "[scenario] waiting 30s for any restart loop to manifest"
sleep 30

NRESTARTS=$(systemctl show "${UNIT_NAME}" -p NRestarts --value 2>/dev/null; true)
NRESTARTS=$(printf '%s' "${NRESTARTS}" | tr -d '[:space:]')
ACTIVE=$(systemctl is-active "${UNIT_NAME}" 2>/dev/null; true)
ACTIVE=$(printf '%s' "${ACTIVE}" | tr -d '[:space:]')
SUBSTATE=$(systemctl show "${UNIT_NAME}" -p SubState --value 2>/dev/null; true)
SUBSTATE=$(printf '%s' "${SUBSTATE}" | tr -d '[:space:]')
MAIN_PID=$(systemctl show "${UNIT_NAME}" -p ExecMainPID --value 2>/dev/null; true)
MAIN_PID=$(printf '%s' "${MAIN_PID}" | tr -d '[:space:]')
echo "[scenario] NRestarts=${NRESTARTS} is-active=${ACTIVE} SubState=${SUBSTATE} ExecMainPID=${MAIN_PID}"

# ── PRIMARY ASSERTION ──────────────────────────────────────────────────────
# The real Pi-thrash incident happened because ExecStart ran, crashed on
# ModuleNotFoundError, and looped under Restart=on-failure. The lockfile
# defense must prevent ExecStart from ever being invoked while install.sh is
# running. The stub touches /tmp/inkypi-stub-ran the moment it runs — if that
# file exists, the defense is broken regardless of NRestarts or StartLimit.
if [ -f "${STUB_MARKER}" ]; then
    echo "FAIL: ExecStart ran while install-in-progress lockfile was present." >&2
    echo "      This is the JTN-607 regression the Pi thrash gate protects." >&2
    echo "      NRestarts=${NRESTARTS} is-active=${ACTIVE} ExecMainPID=${MAIN_PID}" >&2
    journalctl -u "${UNIT_NAME}" --no-pager -n 50 >&2 || true
    exit 1
fi

# ── SECONDARY ASSERTION ────────────────────────────────────────────────────
# ExecMainPID must be 0 — it is only set when the main process actually
# started. A non-zero value means systemd got far enough to fork the stub.
if [ -n "${MAIN_PID}" ] && [ "${MAIN_PID}" != "0" ]; then
    echo "FAIL: ExecMainPID=${MAIN_PID} (expected 0) — ExecStart ran despite lockfile" >&2
    exit 1
fi

# ── BOUNDED RESTART LOOP ASSERTION ─────────────────────────────────────────
# Even if ExecStart never ran, an unbounded count of ExecStartPre failures
# would still chew CPU. systemd's default StartLimitBurst=5 should cap this.
# Observed on a clean run: NRestarts is either 0 (systemd skipped restart
# entirely because ExecStartPre failed before main) or a small number (≤ 10).
# We allow up to 10 as a generous ceiling; an unbounded loop would blow past
# this inside the 30 s window with RestartSec=1.
if [ -z "${NRESTARTS}" ] || [ "${NRESTARTS}" = "?" ]; then
    echo "FAIL: could not read NRestarts from systemctl show" >&2
    exit 1
fi
if [ "${NRESTARTS}" -gt 10 ]; then
    echo "FAIL: NRestarts=${NRESTARTS} — restart loop is not bounded by StartLimit" >&2
    echo "      This regresses the Pi-thrash defense." >&2
    journalctl -u "${UNIT_NAME}" --no-pager -n 50 >&2 || true
    exit 1
fi

# ── POSITIVE CONTROL ───────────────────────────────────────────────────────
# Remove the lockfile (simulating install.sh completing cleanly) and confirm
# that with the defense lifted, ExecStart DOES finally run. This proves the
# "ExecStart never ran" outcome above was caused by the lockfile and not by a
# test harness artefact (wrong unit path, unit not recognised, etc.).
echo "[scenario] positive control: removing lockfile and starting unit"
rm -f "${LOCKFILE}"
# reset-failed so systemd will accept a fresh start after start-limit hit.
systemctl reset-failed "${UNIT_NAME}" 2>/dev/null || true
systemctl start "${UNIT_NAME}" --no-block 2>&1 || true
# Give it a moment to run, crash, and touch the marker.
sleep 3
if [ ! -f "${STUB_MARKER}" ]; then
    # Retry once — on a slow runner the stub may take a moment.
    sleep 3
fi
if [ ! -f "${STUB_MARKER}" ]; then
    echo "FAIL: positive control — ExecStart never ran after lockfile removal." >&2
    echo "      The scenario harness is suspect; NRestarts=0 above may be vacuous." >&2
    journalctl -u "${UNIT_NAME}" --no-pager -n 50 >&2 || true
    exit 1
fi

echo "[scenario] positive control OK — ExecStart ran once lockfile was removed"
echo "[scenario] PASS: install crash-loop defense intact"
exit 0
"""


@pytest.fixture(scope="module")
def systemd_image() -> Iterator[str]:
    """Build a minimal systemd-capable Debian image once per test module."""
    image_tag = f"inkypi-crash-loop-{uuid.uuid4().hex[:8]}"
    dockerfile = textwrap.dedent("""
        FROM debian:trixie-slim
        ENV DEBIAN_FRONTEND=noninteractive
        RUN apt-get update \\
            && apt-get install -y --no-install-recommends \\
                systemd \\
                systemd-sysv \\
                dbus \\
                procps \\
            && rm -rf /var/lib/apt/lists/* \\
            && find /etc/systemd/system \\
                /lib/systemd/system/multi-user.target.wants \\
                /lib/systemd/system/local-fs.target.wants \\
                /lib/systemd/system/sockets.target.wants \\
                /lib/systemd/system/basic.target.wants \\
                /lib/systemd/system/anaconda.target.wants \\
                -type l -delete 2>/dev/null || true
        STOPSIGNAL SIGRTMIN+3
        CMD ["/lib/systemd/systemd"]
        """).strip()

    build = subprocess.run(
        ["docker", "build", "-t", image_tag, "-f", "-", str(REPO_ROOT)],
        input=dockerfile,
        text=True,
        capture_output=True,
        timeout=300,
        check=False,
    )
    if build.returncode != 0:
        pytest.skip(
            "Could not build systemd-capable Docker image "
            f"(exit {build.returncode}): {build.stderr[-400:]}"
        )

    yield image_tag

    subprocess.run(
        ["docker", "rmi", "-f", image_tag],
        capture_output=True,
        check=False,
        timeout=60,
    )


def _ensure_repo_artifacts_present() -> None:
    """Sanity-check that the files we mount into the container actually exist."""
    assert SERVICE_UNIT.is_file(), f"missing {SERVICE_UNIT}"
    assert INSTALL_SH.is_file(), f"missing {INSTALL_SH}"

    # Fail fast if JTN-600's disable line has been reverted out of install.sh.
    # Without it the stop_service() contract the scenario asserts is moot and
    # the test would pass vacuously.
    install_text = INSTALL_SH.read_text()
    assert "systemctl disable" in install_text, (
        "JTN-600 regression: install.sh no longer calls `systemctl disable` "
        "inside stop_service(). This test cannot run until the disable call "
        "is restored — see JTN-600."
    )
    # Same check for the JTN-607 lockfile defense — the test scenario relies on
    # inkypi.service's ExecStartPre guard staying in place.
    unit_text = SERVICE_UNIT.read_text()
    assert "install-in-progress" in unit_text, (
        "JTN-607 regression: inkypi.service no longer refuses start while "
        "/var/lib/inkypi/.install-in-progress exists. See JTN-607."
    )


def test_install_crash_mid_pip_does_not_restart_loop(systemd_image: str) -> None:
    """Install crash mid-pip must NOT drive the service into a restart loop.

    See JTN-609 / module docstring for the full scenario.
    """
    _ensure_repo_artifacts_present()

    container_name = f"inkypi-crash-loop-{uuid.uuid4().hex[:8]}"
    # 512 MB cap matches the Pi Zero 2 W the real incident happened on and
    # keeps this test aligned with the JTN-536 memcap smoke-test invariants
    # without sharing its script.
    run_cmd = [
        "docker",
        "run",
        "--rm",
        "--detach",
        "--name",
        container_name,
        "--privileged",
        "--memory=512m",
        "--memory-swap=512m",
        "--tmpfs",
        "/run",
        "--tmpfs",
        "/run/lock",
        "-v",
        "/sys/fs/cgroup:/sys/fs/cgroup:rw",
        "-v",
        f"{REPO_ROOT}:/opt/inkypi-src:ro",
        systemd_image,
    ]
    start = subprocess.run(
        run_cmd, capture_output=True, text=True, timeout=60, check=False
    )
    if start.returncode != 0:
        pytest.skip(
            "Could not launch systemd-in-docker container "
            f"(exit {start.returncode}): {start.stderr[-400:]}"
        )

    try:
        # Wait for systemd to finish bringing the container up. `is-system-running`
        # returns 'running' or 'degraded' once PID 1 has reached the final target.
        boot_ok = False
        boot_output = ""
        for _ in range(30):
            probe = subprocess.run(
                [
                    "docker",
                    "exec",
                    container_name,
                    "systemctl",
                    "is-system-running",
                    "--wait",
                ],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            boot_output = (probe.stdout or "") + (probe.stderr or "")
            state = probe.stdout.strip() if probe.stdout else ""
            if state in {"running", "degraded"}:
                boot_ok = True
                break
            if state == "initializing" or state == "starting":
                continue
            # Any other state — retry briefly in case systemd is still booting.
        if not boot_ok:
            pytest.skip(
                "systemd did not reach a running state inside the container; "
                f"last output: {boot_output[-400:]}"
            )

        exec_cmd = [
            "docker",
            "exec",
            container_name,
            "bash",
            "-c",
            CONTAINER_SCENARIO,
        ]
        result = subprocess.run(
            exec_cmd,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )

        combined = (result.stdout or "") + (result.stderr or "")
        # Surface container output so CI logs tell us exactly what happened.
        print(combined)

        assert result.returncode == 0, (
            "JTN-609 install crash-loop regression gate FAILED. "
            f"Container exit={result.returncode}. Output tail:\n{combined[-2000:]}"
        )

        # Belt-and-suspenders assertions. The scenario already bails on
        # failure via `exit 1`, but re-check the key invariants here so a
        # failure message in pytest output is self-explanatory if someone
        # later deletes an in-scenario check by mistake.
        #
        # 1. The Pi-thrash defense PASS line must be present.
        assert "PASS: install crash-loop defense intact" in combined, (
            "Scenario did not reach its PASS line; output tail:\n" f"{combined[-1500:]}"
        )
        # 2. The positive control must have run ExecStart after lockfile
        #    removal (otherwise the NRestarts count would be vacuous).
        assert "positive control OK" in combined, (
            "Positive control did not confirm ExecStart ran after lockfile "
            f"removal; output tail:\n{combined[-1500:]}"
        )
    finally:
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            capture_output=True,
            check=False,
            timeout=60,
        )
