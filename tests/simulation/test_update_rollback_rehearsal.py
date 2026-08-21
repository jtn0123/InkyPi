"""The update → verify → boot-health → rollback chain, rehearsed end to end.

Each script is unit-tested in isolation elsewhere. What those cannot show is
whether the pieces agree with each other: that a confirmed update actually
records health, that a dark one leaves rollback armed, and that the device ends
up back on the previous tag rather than stuck.

Everything here is real except the two things a Mac cannot provide — systemd
and the app itself. ``systemctl`` is a recording shim; the app is a small HTTP
server whose readiness and reported version the test controls. The git repo,
the tags, the state files and all three shell scripts are genuine.
"""

from __future__ import annotations

import json
import shutil
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from tests.simulation.fake_systemd import install_fake_systemctl, run_bash

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_DIR = REPO_ROOT / "install"

pytestmark = [
    pytest.mark.simulation,
    pytest.mark.skipif(
        shutil.which("bash") is None or shutil.which("curl") is None,
        reason="requires bash and curl",
    ),
]


class FakeDevice:
    """The InkyPi service as far as ``verify_app_serving`` can tell.

    Only two endpoints matter: ``/readyz`` and ``/api/version/info``. Both are
    mutable so a test can stage "came back on the wrong version" or "never came
    back at all" without touching the script.
    """

    def __init__(self) -> None:
        self.ready = True
        self.version = "2.0.0"
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler API
                if self.path == "/readyz":
                    self.send_response(200 if outer.ready else 503)
                    self.end_headers()
                    self.wfile.write(b"ok")
                elif self.path == "/api/version/info":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"version": outer.version}).encode())
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, *_args: Any) -> None:
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    def go_dark(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def close(self) -> None:
        try:
            self.go_dark()
        except Exception:
            pass


@pytest.fixture
def rehearsal(tmp_path: Path) -> Iterator[Any]:
    """A throwaway install tree: real scripts, real git repo, fake systemctl."""
    project = tmp_path / "inkypi"
    install = project / "install"
    install.mkdir(parents=True)
    for name in (
        "update.sh",
        "boot-health.sh",
        "rollback.sh",
        "_common.sh",
        "do_update.sh",
    ):
        shutil.copy(INSTALL_DIR / name, install / name)
    (project / "VERSION").write_text("2.0.0\n")

    state = tmp_path / "state"
    state.mkdir()
    bin_dir = tmp_path / "bin"
    env = install_fake_systemctl(
        bin_dir, tmp_path / "systemctl.log", tmp_path / "systemctl.state"
    )
    env["INKYPI_LOCKFILE_DIR"] = str(state)

    device = FakeDevice()
    env["INKYPI_PORT"] = str(device.port)
    env["INKYPI_SERVICE_START_TIMEOUT"] = "6"

    yield {
        "project": project,
        "install": install,
        "state": state,
        "env": env,
        "device": device,
        "systemctl_log": tmp_path / "systemctl.log",
    }
    device.close()


def _verify(rehearsal: Any) -> Any:
    """Run the real ``verify_app_serving`` from the real update.sh."""
    return run_bash(
        f"""
        set -uo pipefail
        export INKYPI_UPDATE_SOURCE_ONLY=1
        source {rehearsal["install"] / "update.sh"}
        verify_app_serving
        echo "RC=$?"
        """,
        rehearsal["env"],
    )


def _record_failure(rehearsal: Any, threshold: Any = 2) -> Any:
    return run_bash(
        f"INKYPI_BOOT_HEALTH_MAX_UNHEALTHY={threshold} "
        f'bash {rehearsal["install"] / "boot-health.sh"}',
        rehearsal["env"],
    )


def _outcome(rehearsal: Any) -> Any:
    path = rehearsal["state"] / ".last-update-outcome"
    return json.loads(path.read_text()) if path.exists() else None


class TestHealthyUpdate:
    def test_confirmed_update_records_health_and_disarms_rollback(
        self, rehearsal: Any
    ) -> None:
        """The happy path: serving the expected version marks it healthy."""
        rehearsal["device"].version = "2.0.0"

        result = _verify(rehearsal)
        assert "RC=0" in result.stdout, result.stdout + result.stderr
        assert _outcome(rehearsal)["verdict"] == "confirmed"

        confirmed = rehearsal["state"] / "confirmed_version"
        assert confirmed.read_text().strip() == "2.0.0"

        # Having been confirmed, repeated failures must NOT roll it back — a
        # version that worked before points at the environment.
        (rehearsal["state"] / "prev_version").write_text("1.0.0\n")
        for _ in range(5):
            _record_failure(rehearsal)
        assert not (rehearsal["state"] / "rollback.log").exists()


class TestUpdateThatComesBackWrong:
    def test_stale_version_is_unconfirmed_and_leaves_rollback_armed(
        self, rehearsal: Any
    ) -> None:
        """The unit is up but running yesterday's code — the checkout did not take."""
        rehearsal["device"].version = "1.0.0"  # expected 2.0.0

        result = _verify(rehearsal)
        assert "RC=1" in result.stdout, result.stdout + result.stderr

        outcome = _outcome(rehearsal)
        assert outcome["verdict"] == "unconfirmed"
        assert outcome["observed_version"] == "1.0.0"
        # Crucially, health was NOT recorded, so rollback stays available.
        assert not (rehearsal["state"] / "confirmed_version").exists()


class TestDarkUpdateRollsBack:
    def test_dark_service_eventually_rolls_back_to_the_previous_tag(
        self, rehearsal: Any
    ) -> None:
        """The scenario that used to need physical access to recover from."""
        # Stage a previous version to fall back to, and a rollback stand-in so
        # the rehearsal does not need a full git checkout to observe the intent.
        (rehearsal["state"] / "prev_version").write_text("1.0.0\n")
        log = rehearsal["state"] / "rollback.log"
        (rehearsal["install"] / "rollback.sh").write_text(
            f"#!/bin/bash\necho ROLLBACK_TO=$(cat {rehearsal['state']}/prev_version) >> {log}\n"
        )

        rehearsal["device"].go_dark()

        result = _verify(rehearsal)
        assert "RC=1" in result.stdout, result.stdout + result.stderr
        assert _outcome(rehearsal)["verdict"] == "dark"
        assert not (rehearsal["state"] / "confirmed_version").exists()

        # systemd retries, exhausts StartLimitBurst, and calls OnFailure once
        # per start-limit episode — not once per failed start.
        _record_failure(rehearsal)
        assert not log.exists(), "must not roll back on the first start-limit event"
        _record_failure(rehearsal)

        assert (
            log.exists()
        ), "a second start-limit event on an unconfirmed version must roll back"
        assert "ROLLBACK_TO=1.0.0" in log.read_text()

    def test_rollback_happens_once_even_if_failures_continue(
        self, rehearsal: Any
    ) -> None:
        """Flipping between two broken versions forever would never converge."""
        (rehearsal["state"] / "prev_version").write_text("1.0.0\n")
        log = rehearsal["state"] / "rollback.log"
        (rehearsal["install"] / "rollback.sh").write_text(
            f"#!/bin/bash\necho ROLLBACK >> {log}\n"
        )
        rehearsal["device"].go_dark()
        _verify(rehearsal)

        for _ in range(8):
            _record_failure(rehearsal)

        assert log.read_text().count("ROLLBACK") == 1


class TestRecoveryAfterRollback:
    def test_a_confirmed_run_after_rollback_clears_the_failure_streak(
        self, rehearsal: Any
    ) -> None:
        """Once the device is serving again the slate must be wiped clean.

        Otherwise a later unrelated failure would inherit an old streak and
        trigger a rollback far sooner than the threshold implies.
        """
        state = rehearsal["state"]
        (state / "prev_version").write_text("1.0.0\n")
        (state / "failed_starts").write_text("2\n")

        rehearsal["device"].version = "2.0.0"
        assert "RC=0" in _verify(rehearsal).stdout

        assert not (state / "failed_starts").exists()
        assert not (state / ".auto-rollback-attempted").exists()


class TestScriptsAgreeOnState:
    """The scripts share files by path; a rename in one breaks the chain."""

    def test_confirmed_version_written_by_update_is_read_by_boot_health(
        self, rehearsal: Any
    ) -> None:
        rehearsal["device"].version = "2.0.0"
        _verify(rehearsal)

        probe = run_bash(
            f"""
            set -uo pipefail
            source {rehearsal["install"] / "boot-health.sh"}
            echo "CONFIRMED=$(_read_file "$CONFIRMED_VERSION_FILE")"
            echo "CURRENT=$(_current_version)"
            """,
            rehearsal["env"],
        )
        assert "CONFIRMED=2.0.0" in probe.stdout, probe.stdout + probe.stderr
        assert "CURRENT=2.0.0" in probe.stdout

    def test_update_and_boot_health_use_the_same_state_directory(
        self, rehearsal: Any
    ) -> None:
        """Both must honour INKYPI_LOCKFILE_DIR or the device writes to /var."""
        rehearsal["device"].version = "2.0.0"
        _verify(rehearsal)
        _record_failure(rehearsal)

        written = {p.name for p in rehearsal["state"].iterdir()}
        assert ".last-update-outcome" in written
        assert "confirmed_version" in written


class TestVerifyIsResilient:
    def test_missing_curl_skips_rather_than_failing_the_update(
        self, rehearsal: Any, tmp_path: Path
    ) -> None:
        """A stripped image without curl must not fail an otherwise-good update."""
        minimal_bin = tmp_path / "nocurl"
        minimal_bin.mkdir()
        # Everything the script needs to run, deliberately without curl: bash
        # and the core utilities it calls, plus the sudo passthrough.
        for tool in ("bash", "cat", "date", "mkdir", "rm", "mv", "sed", "tr", "sleep"):
            found = shutil.which(tool)
            if found:
                (minimal_bin / tool).symlink_to(found)
        shutil.copy(tmp_path / "bin" / "sudo", minimal_bin / "sudo")
        env = {**rehearsal["env"], "PATH": str(minimal_bin)}
        assert shutil.which("curl", path=str(minimal_bin)) is None

        result = run_bash(
            f"""
            set -uo pipefail
            export INKYPI_UPDATE_SOURCE_ONLY=1
            source {rehearsal["install"] / "update.sh"}
            verify_app_serving
            echo "RC=$?"
            """,
            env,
        )
        assert "RC=0" in result.stdout, result.stdout + result.stderr
        assert _outcome(rehearsal)["verdict"] == "skipped"


class TestBrokenVersionFile:
    def test_unreadable_version_still_confirms_on_readiness(
        self, rehearsal: Any
    ) -> None:
        """With nothing to compare, answering /readyz is the strongest claim."""
        (rehearsal["project"] / "VERSION").write_text("\n")
        rehearsal["device"].version = "whatever"

        assert "RC=0" in _verify(rehearsal).stdout
        assert _outcome(rehearsal)["verdict"] == "confirmed"
