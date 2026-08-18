"""Cover for install/boot-health.sh — unattended rollback after failed starts.

rollback.sh has always worked, but only when a human ran it or clicked it in
the settings UI. A device that updates itself into a non-starting state cannot
serve the UI that offers the button, so recovery required physical access.

The decision rule is kept free of filesystem and systemd access (mirroring
boot_health.h in the ESP32-Garage-Fan firmware) so it can be tested directly
rather than through a simulated failing install.
"""

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BOOT_HEALTH_SH = REPO_ROOT / "install" / "boot-health.sh"
FAILURE_UNIT = REPO_ROOT / "install" / "inkypi-failure.service"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="requires bash")


def _decide(failed_starts: Any, running_confirmed: Any, threshold: Any = 2) -> Any:
    """Invoke the pure decision function; returns True when it says roll back."""
    script = f"""
    set -uo pipefail
    export INKYPI_BOOT_HEALTH_MAX_UNHEALTHY={threshold}
    source {BOOT_HEALTH_SH!s}
    if boot_health_should_rollback "{failed_starts}" "{running_confirmed}"; then
        echo DECISION=rollback
    else
        echo DECISION=hold
    fi
    """
    proc = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, proc.stderr
    return "DECISION=rollback" in proc.stdout


class TestDecisionRule:
    def test_holds_below_the_threshold(self) -> None:
        assert _decide(1, "no") is False

    def test_rolls_back_at_the_threshold(self) -> None:
        assert _decide(2, "no") is True
        assert _decide(9, "no") is True

    def test_default_threshold_is_two_start_limit_events(self) -> None:
        """Each event is already StartLimitBurst failed starts, not one.

        systemd calls OnFailure= once when the unit exhausts its start limit,
        so a threshold of 3 would have needed three separate episodes across
        multiple boots before recovering.
        """
        import subprocess

        out = subprocess.run(
            [
                "bash",
                "-c",
                f"source {BOOT_HEALTH_SH!s}; " "echo $BOOT_HEALTH_MAX_UNHEALTHY",
            ],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        assert out == "2"

    def test_a_confirmed_version_never_rolls_back(self) -> None:
        """If a version worked before, the environment is the suspect.

        Swapping versions would regress the install without fixing the actual
        cause — a full disk, a yanked SD card, a broken OS dependency.
        """
        assert _decide(2, "yes") is False
        assert _decide(99, "yes") is False

    def test_threshold_is_configurable(self) -> None:
        assert _decide(2, "no", threshold=2) is True
        assert _decide(2, "no", threshold=5) is False

    def test_garbage_counter_does_not_trigger_a_rollback(self) -> None:
        assert _decide("", "no") is False
        assert _decide("abc", "no") is False


class TestFailureAccounting:
    """The stateful half: counting failures and firing rollback exactly once."""

    def _stage(
        self,
        tmp_path: Path,
        *,
        version: Any,
        confirmed: Any = None,
        prev_version: Any = "1.0.0",
    ) -> Any:
        install_dir = tmp_path / "install"
        install_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(BOOT_HEALTH_SH, install_dir / "boot-health.sh")
        (tmp_path / "VERSION").write_text(version + "\n")

        state = tmp_path / "state"
        state.mkdir(exist_ok=True)
        if confirmed is not None:
            (state / "confirmed_version").write_text(confirmed + "\n")
        if prev_version is not None:
            (state / "prev_version").write_text(prev_version + "\n")

        # Stand-in for rollback.sh that records that it ran.
        (install_dir / "rollback.sh").write_text(
            f"#!/bin/bash\necho ROLLBACK_RAN >> {state / 'rollback.log'!s}\n"
        )
        return install_dir, state

    def _record_failure(self, install_dir: Any, state: Any, threshold: Any = 3) -> Any:
        script = f"""
        set -uo pipefail
        export INKYPI_LOCKFILE_DIR={state!s}
        export INKYPI_BOOT_HEALTH_MAX_UNHEALTHY={threshold}
        bash {install_dir / "boot-health.sh"!s}
        """
        proc = subprocess.run(
            ["bash", "-c", script], capture_output=True, text=True, timeout=60
        )
        # Every path through boot-health.sh — hold and rollback alike — exits 0.
        # Without this, a script that died early would still satisfy the
        # "rollback.log is absent" assertions and look like a passing hold.
        assert proc.returncode == 0, proc.stderr
        return proc

    def test_counter_increments_and_rollback_fires_at_the_threshold(
        self, tmp_path: Path
    ) -> None:
        install_dir, state = self._stage(tmp_path, version="2.0.0", confirmed="1.0.0")

        self._record_failure(install_dir, state)
        assert (state / "failed_starts").read_text().strip() == "1"
        assert not (state / "rollback.log").exists()

        self._record_failure(install_dir, state)
        assert (state / "failed_starts").read_text().strip() == "2"
        assert not (state / "rollback.log").exists()

        self._record_failure(install_dir, state)
        assert (state / "failed_starts").read_text().strip() == "3"
        assert "ROLLBACK_RAN" in (state / "rollback.log").read_text()

    def test_confirmed_version_is_never_rolled_back(self, tmp_path: Path) -> None:
        # Running version equals the last confirmed-healthy one.
        install_dir, state = self._stage(tmp_path, version="2.0.0", confirmed="2.0.0")
        for _ in range(5):
            self._record_failure(install_dir, state)
        assert not (state / "rollback.log").exists()

    def test_rollback_is_attempted_only_once(self, tmp_path: Path) -> None:
        """Flipping between two broken versions forever would never converge."""
        install_dir, state = self._stage(tmp_path, version="2.0.0", confirmed="1.0.0")
        for _ in range(6):
            self._record_failure(install_dir, state)
        log = (state / "rollback.log").read_text()
        assert log.count("ROLLBACK_RAN") == 1, log

    def test_no_previous_version_means_no_rollback(self, tmp_path: Path) -> None:
        install_dir, state = self._stage(
            tmp_path, version="2.0.0", confirmed="1.0.0", prev_version=None
        )
        for _ in range(4):
            self._record_failure(install_dir, state)
        assert not (state / "rollback.log").exists()

    def test_marking_confirmed_clears_the_streak(self, tmp_path: Path) -> None:
        install_dir, state = self._stage(tmp_path, version="2.0.0", confirmed="1.0.0")
        self._record_failure(install_dir, state)
        self._record_failure(install_dir, state)
        assert (state / "failed_starts").read_text().strip() == "2"

        script = f"""
        set -uo pipefail
        export INKYPI_LOCKFILE_DIR={state!s}
        source {install_dir / "boot-health.sh"!s}
        boot_health_mark_confirmed "2.0.0"
        """
        proc = subprocess.run(
            ["bash", "-c", script], capture_output=True, text=True, timeout=60
        )
        assert proc.returncode == 0, proc.stderr
        assert not (state / "failed_starts").exists()
        assert (state / "confirmed_version").read_text().strip() == "2.0.0"

        # And having been confirmed, it must now survive repeated failures.
        for _ in range(5):
            self._record_failure(install_dir, state)
        assert not (state / "rollback.log").exists()


def test_failure_unit_invokes_boot_health_without_masking_the_sentinel() -> None:
    unit = FAILURE_UNIT.read_text()
    assert "boot-health.sh" in unit, "failure unit should invoke boot-health.sh"
    assert ".start-limit-hit" in unit, "the sentinel write must remain"
    # '-' prefix keeps a boot-health problem from failing the unit and hiding
    # the sentinel, which is the load-bearing signal.
    assert "ExecStart=-" in unit, "boot-health invocation must be failure-tolerant"


def test_update_script_records_confirmation_for_boot_health() -> None:
    update_sh = (REPO_ROOT / "install" / "update.sh").read_text()
    assert "_inkypi_mark_boot_health_confirmed" in update_sh
    # Only the confirmed branches may mark health; a dark or stale-version
    # outcome must leave the version unconfirmed so rollback stays armed.
    assert update_sh.count('_inkypi_mark_boot_health_confirmed "') == 2
