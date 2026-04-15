# pyright: reportMissingImports=false
"""Regression tests for JTN-704 — trap-cleanup lockfile + record failure cause.

`install/update.sh` used to leave `/var/lib/inkypi/.install-in-progress` in
place whenever anything failed (OOM, pip failure, CSS failure, etc.). The
systemd unit's ExecStartPre refuses to start while the lockfile exists, so
the service stayed disabled and the user had to `rm` the lockfile by hand.
Worse, the *reason* for the failure was only in the system journal — the UI
had no way to surface it.

JTN-704 inverts this: the EXIT trap *unconditionally* removes the lockfile on
every exit, and on non-zero exit it writes
`/var/lib/inkypi/.last-update-failure` with JSON metadata describing what
failed. This test is the regression gate.

Strategy
--------
We drive `install/update.sh` under a test-only env-var hook
(`INKYPI_UPDATE_TEST_FAIL_AT=<step>`) that `exit 97`s at a named phase after
the trap is installed. The lockfile directory is redirected via
`INKYPI_LOCKFILE_DIR` so no real `/var/lib/inkypi` state is touched. We then
assert the trap honoured JTN-704's contract:

* Lockfile is gone after the failure.
* `.last-update-failure` exists and parses as JSON with the required keys.
* `exit_code` matches the injected exit (97).
* `last_command` matches the injected step label.

A parallel success-path test uses `INKYPI_UPDATE_TEST_EXIT_AFTER_TRAP=1` to
exit 0 right after the trap is registered and asserts the trap's success
branch fires: lockfile removed AND stale `.last-update-failure` cleared.

These env-var hooks are guarded by `[ -n "${VAR:-}" ]` checks at the top of
update.sh, so setting neither leaves production behavior unchanged.
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
UPDATE_SH = REPO_ROOT / "install" / "update.sh"


@pytest.fixture
def lockfile_dir(tmp_path: Path) -> Path:
    """Isolated replacement for /var/lib/inkypi."""
    d = tmp_path / "state"
    d.mkdir()
    return d


def _run_update(
    lockfile_dir: Path,
    env_overrides: dict[str, str],
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    """Invoke install/update.sh with the given env overrides.

    We inherit the current env (PATH etc.) so bash/python3/systemctl are
    resolvable if present, then layer the overrides on top.
    """
    if not shutil.which("bash"):
        pytest.skip("bash is not available on this host")
    env = dict(os.environ)
    env.update(
        {
            "INKYPI_LOCKFILE_DIR": str(lockfile_dir),
            **env_overrides,
        }
    )
    return subprocess.run(
        ["bash", str(UPDATE_SH)],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


class TestFailurePath:
    """Exit != 0 must remove lockfile and write a parseable failure record."""

    def test_injected_startup_failure_removes_lockfile(
        self, lockfile_dir: Path
    ) -> None:
        proc = _run_update(
            lockfile_dir,
            {"INKYPI_UPDATE_TEST_FAIL_AT": "startup"},
        )
        # The injection hook exits 97 explicitly.
        assert proc.returncode == 97, (
            f"expected exit 97 from injection hook, got {proc.returncode}. "
            f"stderr: {proc.stderr!r}"
        )
        lockfile = lockfile_dir / ".install-in-progress"
        assert not lockfile.exists(), (
            f"EXIT trap must remove the lockfile on failure (JTN-704); "
            f"found {lockfile} still present"
        )

    def test_injected_failure_writes_last_update_failure_json(
        self, lockfile_dir: Path
    ) -> None:
        proc = _run_update(
            lockfile_dir,
            {"INKYPI_UPDATE_TEST_FAIL_AT": "startup"},
        )
        assert proc.returncode != 0
        failure_file = lockfile_dir / ".last-update-failure"
        assert failure_file.exists(), (
            f"EXIT trap must write .last-update-failure on non-zero exit "
            f"(JTN-704). stderr: {proc.stderr!r}"
        )
        raw = failure_file.read_text()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:  # pragma: no cover — diagnostic
            pytest.fail(f"failure record is not valid JSON: {exc}. contents: {raw!r}")
        # Required top-level keys for downstream parsers (UI, diagnostics).
        for key in ("timestamp", "exit_code", "last_command", "recent_journal_lines"):
            assert key in parsed, (
                f"failure JSON missing required key {key!r}; got keys "
                f"{sorted(parsed.keys())}"
            )
        assert parsed["exit_code"] == 97, (
            f"exit_code in failure record must match the injected exit (97); "
            f"got {parsed['exit_code']!r}"
        )
        assert parsed["last_command"] == "startup", (
            f"last_command must match injected step label 'startup'; "
            f"got {parsed['last_command']!r}"
        )
        assert (
            isinstance(parsed["timestamp"], str) and parsed["timestamp"]
        ), "timestamp must be a non-empty string"

    def test_failure_at_later_step_records_that_step(self, lockfile_dir: Path) -> None:
        # Injecting at a later step name exercises a different code path — the
        # hook is consulted multiple times as _current_step is updated. This
        # guards against regressions that only set _current_step once.
        #
        # "apt_install" is reachable on any host because the injection fires
        # before the apt command actually runs. We pair it with a brief stub
        # on PATH so the preceding `stop_service` (which tries `systemctl`)
        # does not crash on non-systemd hosts like macOS.
        proc = _run_update(
            lockfile_dir,
            {
                "INKYPI_UPDATE_TEST_FAIL_AT": "apt_install",
                # Prepend a tmp bin with a harmless systemctl stub so
                # stop_service() doesn't abort the script before we reach
                # the injection point.
                "PATH": _systemctl_stub_path()
                + os.pathsep
                + os.environ.get("PATH", ""),
            },
        )
        assert (
            proc.returncode == 97
        ), f"expected exit 97; got {proc.returncode}. stderr: {proc.stderr!r}"
        failure_file = lockfile_dir / ".last-update-failure"
        assert failure_file.exists()
        parsed = json.loads(failure_file.read_text())
        assert parsed["last_command"] == "apt_install"
        assert parsed["exit_code"] == 97
        assert not (lockfile_dir / ".install-in-progress").exists()


class TestSuccessPath:
    """Exit 0 must clear lockfile and stale failure record."""

    def test_success_exit_removes_lockfile(self, lockfile_dir: Path) -> None:
        proc = _run_update(
            lockfile_dir,
            {"INKYPI_UPDATE_TEST_EXIT_AFTER_TRAP": "1"},
        )
        assert proc.returncode == 0, (
            f"success simulation must exit 0; got {proc.returncode}. "
            f"stderr: {proc.stderr!r}"
        )
        assert not (
            lockfile_dir / ".install-in-progress"
        ).exists(), "EXIT trap must remove the lockfile on success (JTN-704)"

    def test_success_exit_clears_stale_failure_record(self, lockfile_dir: Path) -> None:
        stale = lockfile_dir / ".last-update-failure"
        stale.write_text('{"timestamp":"old","exit_code":1}')
        proc = _run_update(
            lockfile_dir,
            {"INKYPI_UPDATE_TEST_EXIT_AFTER_TRAP": "1"},
        )
        assert proc.returncode == 0
        assert not stale.exists(), (
            "Success-path trap must clear any stale .last-update-failure so "
            "downstream consumers see a clean signal (JTN-704)"
        )

    def test_success_exit_does_not_create_failure_record(
        self, lockfile_dir: Path
    ) -> None:
        proc = _run_update(
            lockfile_dir,
            {"INKYPI_UPDATE_TEST_EXIT_AFTER_TRAP": "1"},
        )
        assert proc.returncode == 0
        assert not (
            lockfile_dir / ".last-update-failure"
        ).exists(), "Success path must never create .last-update-failure (JTN-704)"


class TestSuccessFastHook:
    """JTN-724: ``INKYPI_UPDATE_TEST_SUCCESS_FAST`` — happy-path simulation.

    The journey happy-path test (tests/integration/journeys/
    test_update_flow_happy_path.py) needs a way to drive update.sh to a clean
    "completed successfully" terminal state without invoking real git / apt /
    pip / systemctl work. The hook mirrors the existing FAIL_AT /
    EXIT_AFTER_TRAP test hooks: guarded at the top of update.sh by an explicit
    ``[ -n "${INKYPI_UPDATE_TEST_SUCCESS_FAST:-}" ]`` check so production
    callers (which never set the var) are unaffected.
    """

    def test_success_fast_exits_zero(self, lockfile_dir: Path) -> None:
        proc = _run_update(
            lockfile_dir,
            {"INKYPI_UPDATE_TEST_SUCCESS_FAST": "1"},
        )
        assert proc.returncode == 0, (
            f"SUCCESS_FAST hook must exit 0; got {proc.returncode}. "
            f"stderr: {proc.stderr!r}"
        )

    def test_success_fast_writes_success_sentinel(self, lockfile_dir: Path) -> None:
        proc = _run_update(
            lockfile_dir,
            {
                "INKYPI_UPDATE_TEST_SUCCESS_FAST": "1",
                "INKYPI_UPDATE_TEST_TARGET": "v9.9.9",
            },
        )
        assert proc.returncode == 0
        sentinel = lockfile_dir / ".last-update-success"
        assert (
            sentinel.exists()
        ), f"SUCCESS_FAST must write {sentinel}. stderr: {proc.stderr!r}"
        parsed = json.loads(sentinel.read_text())
        assert parsed["mode"] == "test_success_fast"
        assert parsed["target_version"] == "v9.9.9"
        assert isinstance(parsed["timestamp"], str) and parsed["timestamp"]

    def test_success_fast_removes_lockfile(self, lockfile_dir: Path) -> None:
        proc = _run_update(
            lockfile_dir,
            {"INKYPI_UPDATE_TEST_SUCCESS_FAST": "1"},
        )
        assert proc.returncode == 0
        assert not (
            lockfile_dir / ".install-in-progress"
        ).exists(), "EXIT trap must remove the lockfile on SUCCESS_FAST exit"

    def test_success_fast_clears_stale_failure_record(self, lockfile_dir: Path) -> None:
        stale = lockfile_dir / ".last-update-failure"
        stale.write_text('{"timestamp":"old","exit_code":1}')
        proc = _run_update(
            lockfile_dir,
            {"INKYPI_UPDATE_TEST_SUCCESS_FAST": "1"},
        )
        assert proc.returncode == 0
        assert not stale.exists(), (
            "SUCCESS_FAST path is a successful exit, so the EXIT trap must "
            "clear any stale .last-update-failure"
        )

    def test_success_fast_does_not_run_real_work(self, lockfile_dir: Path) -> None:
        """Hook must exit before touching apt/git/systemctl.

        We look for telltale output that would appear if stop_service or
        apt_install had run. The success-fast branch prints a single TEST:
        line to stderr and then exits 0 — nothing else should be emitted.
        """
        proc = _run_update(
            lockfile_dir,
            {"INKYPI_UPDATE_TEST_SUCCESS_FAST": "1"},
        )
        assert proc.returncode == 0
        combined = proc.stdout + proc.stderr
        for forbidden in (
            "Stopping service",
            "Installing system dependencies",
            "apt-get install",
            "Creating virtual environment",
        ):
            assert forbidden not in combined, (
                f"SUCCESS_FAST must short-circuit before {forbidden!r} runs; "
                f"found it in output: {combined!r}"
            )

    def test_success_fast_unset_does_not_trigger_sentinel(
        self, lockfile_dir: Path
    ) -> None:
        """Production parity: with the hook unset, EXIT_AFTER_TRAP must NOT
        create the success sentinel. This guards against a future refactor
        that accidentally wires both hooks together."""
        proc = _run_update(
            lockfile_dir,
            {"INKYPI_UPDATE_TEST_EXIT_AFTER_TRAP": "1"},
        )
        assert proc.returncode == 0
        assert not (lockfile_dir / ".last-update-success").exists(), (
            "Only INKYPI_UPDATE_TEST_SUCCESS_FAST should create "
            ".last-update-success; EXIT_AFTER_TRAP must not."
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_SYSTEMCTL_STUB_DIR: Path | None = None


def _systemctl_stub_path() -> str:
    """Return a directory containing a no-op ``systemctl`` shim on PATH.

    On macOS / CI hosts without systemd, _common.sh's ``stop_service`` would
    error out before the test injection point is reached. A harmless stub
    that returns success keeps the script flowing to the injection hook
    without altering the trap's behavior.
    """
    global _SYSTEMCTL_STUB_DIR
    if _SYSTEMCTL_STUB_DIR is not None and (_SYSTEMCTL_STUB_DIR / "systemctl").exists():
        return str(_SYSTEMCTL_STUB_DIR)
    # pytest's tmp_path fixture is per-test; we want a stable location shared
    # across the module. Use the interpreter-global site-tmpdir.
    import tempfile

    d = Path(tempfile.mkdtemp(prefix="inkypi-jtn704-stub-"))
    stub = d / "systemctl"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        "# JTN-704 test stub: pretend systemctl succeeded.\n"
        "exit 0\n"
    )
    stub.chmod(0o755)
    _SYSTEMCTL_STUB_DIR = d
    return str(d)


if __name__ == "__main__":  # pragma: no cover — manual debugging
    sys.exit(pytest.main([__file__, "-v"]))
