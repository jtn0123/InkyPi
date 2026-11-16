"""A refused update or rollback never ends a run that is going (A4).

The update state machine lives in ``services.updates``. These tests pin the
rules the routes now only translate:

* a refused rollback or update leaves the running state exactly as it was;
* a request that fails after claiming the run undoes only its own claim;
* the Roll back button and the rollback route share one eligibility rule;
* a run's unit that outlives a service restart is still reported running.
"""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from flask.testing import FlaskClient

from services import updates

_BUSY_UNIT = "inkypi-update-busy.service"


@pytest.fixture(autouse=True)
def fresh_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[dict[str, object]]:
    """A private run state, state dir and no systemd for every test."""
    state: dict[str, object] = {
        "running": False,
        "unit": None,
        "started_at": None,
        "last_unit": None,
        "kind": None,
    }
    monkeypatch.setattr(updates, "_UPDATE_STATE", state)
    monkeypatch.setattr(updates, "_systemd_available", lambda: False)
    monkeypatch.setenv("INKYPI_LOCKFILE_DIR", str(tmp_path))
    yield state


def _write_failure(tmp_path: Path, last_command: str = "apt_install") -> None:
    record = {
        "timestamp": "2026-11-16T10:00:00Z",
        "exit_code": 97,
        "last_command": last_command,
        "recent_journal_lines": "apt-get: failed",
    }
    (tmp_path / ".last-update-failure").write_text(json.dumps(record))


def _write_prev_version(tmp_path: Path, tag: str = "v1.2.2") -> None:
    (tmp_path / "prev_version").write_text(tag)


def _mark_running(state: dict[str, object]) -> dict[str, object]:
    """Put an update in progress and return a copy to compare against."""
    state.update(
        running=True,
        unit=_BUSY_UNIT,
        started_at=time.time() - 5,
        kind="update",
    )
    return dict(state)


class TestRefusalsKeepTheRunningState:
    def test_refused_rollback_without_failure_keeps_update_running(
        self, client: FlaskClient, fresh_state: dict[str, object], tmp_path: Path
    ) -> None:
        """The grade report's case: no failure file, an update running."""
        _write_prev_version(tmp_path)
        before = _mark_running(fresh_state)

        resp = client.post("/settings/update/rollback")

        assert resp.status_code == 409
        assert resp.get_json()["code"] == "no_failure"
        assert fresh_state == before
        # The guard still holds: a second update is refused too.
        again = client.post("/settings/update")
        assert again.status_code == 409
        assert again.get_json()["running"] is True
        assert again.get_json()["unit"] == _BUSY_UNIT

    @pytest.mark.parametrize(
        ("last_command", "prev_version", "code"),
        [
            ("preflight: only 120 MB free on /", "v1.2.2", "preflight_abort"),
            ("apt_install", None, "no_prev_version"),
            ("apt_install", "v1.2.2", "already_running"),
        ],
    )
    def test_every_rollback_refusal_keeps_update_running(
        self,
        client: FlaskClient,
        fresh_state: dict[str, object],
        tmp_path: Path,
        last_command: str,
        prev_version: str | None,
        code: str,
    ) -> None:
        _write_failure(tmp_path, last_command)
        if prev_version is not None:
            _write_prev_version(tmp_path, prev_version)
        before = _mark_running(fresh_state)

        resp = client.post("/settings/update/rollback")

        assert resp.status_code == 409
        assert resp.get_json()["code"] == code
        assert fresh_state == before

    def test_refused_update_keeps_the_running_update(
        self, client: FlaskClient, fresh_state: dict[str, object]
    ) -> None:
        before = _mark_running(fresh_state)

        resp = client.post("/settings/update")

        assert resp.status_code == 409
        body = resp.get_json()
        assert body["code"] == "already_running"
        assert "already in progress" in body["error"]
        assert fresh_state == before

    def test_service_refusal_changes_nothing(
        self, fresh_state: dict[str, object], tmp_path: Path
    ) -> None:
        before = _mark_running(fresh_state)

        result = updates.start_rollback()

        assert result.refusal is not None
        assert result.refusal.code == "no_failure"
        assert result.unit == _BUSY_UNIT
        assert fresh_state == before


class TestOnlyTheOwnerEndsARun:
    def test_failed_update_launch_releases_its_claim(
        self,
        client: FlaskClient,
        fresh_state: dict[str, object],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A launch that raises must not leave the guard stuck on running."""

        def _boom(script_path: Any, target_tag: Any = None) -> None:
            raise RuntimeError("thread start failed")

        monkeypatch.setattr(updates, "_start_update_fallback_thread", _boom)

        resp = client.post("/settings/update")

        assert resp.status_code == 500
        assert fresh_state["running"] is False

    def test_finish_leaves_a_newer_run_alone(
        self, fresh_state: dict[str, object]
    ) -> None:
        first = updates.try_begin("update")
        assert first is not None
        # The reaper ends the first run and another request starts a new one.
        updates._set_update_state(False, None)
        second = updates.try_begin("rollback")
        assert second is not None
        after_second = dict(fresh_state)

        assert updates.finish(first) is False
        assert fresh_state == after_second
        assert updates.finish(second) is True
        assert fresh_state["running"] is False

    def test_try_begin_refuses_while_running(
        self, fresh_state: dict[str, object]
    ) -> None:
        before = _mark_running(fresh_state)
        assert updates.try_begin("rollback") is None
        assert fresh_state == before

    def test_late_unit_is_not_recorded_on_another_run(
        self, fresh_state: dict[str, object]
    ) -> None:
        ticket = updates.try_begin("update")
        assert ticket is not None
        updates._set_update_state(False, None)
        assert updates.try_begin("update") is not None

        updates._record_unit(ticket, "inkypi-update-1.service")

        assert fresh_state["unit"] is None


class TestRollbackEligibility:
    def test_rule(self) -> None:
        failure = {"last_command": "apt_install"}
        assert updates.rollback_eligibility(failure, "v1.2.2") is None
        # An unreadable record still shows the last update failed.
        assert updates.rollback_eligibility({"parse_error": True}, "v1.2.2") is None
        refusal = updates.rollback_eligibility(None, "v1.2.2")
        assert refusal is not None and refusal.code == "no_failure"
        refusal = updates.rollback_eligibility(
            {"last_command": "preflight: disk"}, "v1.2.2"
        )
        assert refusal is not None and refusal.code == "preflight_abort"
        refusal = updates.rollback_eligibility(failure, None)
        assert refusal is not None and refusal.code == "no_prev_version"

    def test_status_reports_eligible_rollback(
        self, client: FlaskClient, tmp_path: Path
    ) -> None:
        _write_failure(tmp_path)
        _write_prev_version(tmp_path)

        data = client.get("/settings/update_status").get_json()

        assert data["rollback_eligible"] is True
        assert data["running"] is False
        assert data["kind"] is None

    def test_status_not_eligible_after_preflight_abort(
        self, client: FlaskClient, tmp_path: Path
    ) -> None:
        _write_failure(tmp_path, "preflight: only 120 MB free on /")
        _write_prev_version(tmp_path)

        data = client.get("/settings/update_status").get_json()

        assert data["last_failure"]["last_command"].startswith("preflight:")
        assert data["rollback_eligible"] is False

    def test_status_not_eligible_while_running(
        self, client: FlaskClient, fresh_state: dict[str, object], tmp_path: Path
    ) -> None:
        _write_failure(tmp_path)
        _write_prev_version(tmp_path)
        _mark_running(fresh_state)

        data = client.get("/settings/update_status").get_json()

        assert data["running"] is True
        assert data["kind"] == "update"
        assert data["rollback_eligible"] is False

    def test_journal_synthesized_failure_offers_no_rollback(
        self,
        client: FlaskClient,
        fresh_state: dict[str, object],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """The route needs the failure file, so the button must not appear
        for a failure that only the journal shows."""
        _write_prev_version(tmp_path)
        fresh_state.update(
            running=True,
            unit="inkypi-update-1234.service",
            started_at=time.time() - 60,
            kind="update",
        )
        monkeypatch.setattr(updates, "_systemd_available", lambda: True)

        def fake_run(cmd: list[str], *args: Any, **kwargs: Any) -> Any:
            out = {"is-active": "failed\n"}.get(cmd[1], "")
            if cmd[0] == "journalctl":
                out = "do_update.sh: checkout failed\n"
            return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)

        data = client.get("/settings/update_status").get_json()

        assert data["running"] is False
        assert data["last_failure"]["synthesized"] is True
        assert data["rollback_eligible"] is False
        assert client.post("/settings/update/rollback").get_json()["code"] == (
            "no_failure"
        )


class TestRunSurvivesServiceRestart:
    """An update restarts this service while its unit keeps going."""

    def _list_units(
        self, monkeypatch: pytest.MonkeyPatch, stdout: str
    ) -> list[list[str]]:
        calls: list[list[str]] = []

        def fake_run(cmd: list[str], *args: Any, **kwargs: Any) -> Any:
            calls.append(cmd)
            if cmd[:2] == ["systemctl", "list-units"]:
                return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")
            # is-active for the adopted unit: still going.
            return subprocess.CompletedProcess(cmd, 0, stdout="active\n", stderr="")

        monkeypatch.setattr(updates, "_systemd_available", lambda: True)
        monkeypatch.setattr(subprocess, "run", fake_run)
        return calls

    def test_status_adopts_the_running_unit(
        self,
        client: FlaskClient,
        fresh_state: dict[str, object],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        launched = int(time.time()) - 90
        older = launched - 30
        self._list_units(
            monkeypatch,
            f"inkypi-rollback-{older}.service loaded active running x\n"
            f"inkypi-update-{launched}.service loaded active running /bin/bash\n",
        )

        data = client.get("/settings/update_status").get_json()

        assert data["running"] is True
        assert data["kind"] == "update"
        assert data["unit"] == f"inkypi-update-{launched}.service"
        assert data["started_at"] == float(launched)
        # And a new update is refused while it runs.
        resp = client.post("/settings/update")
        assert resp.status_code == 409
        assert resp.get_json()["unit"] == f"inkypi-update-{launched}.service"

    def test_adopted_rollback_reports_its_kind(
        self, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        launched = int(time.time()) - 10
        self._list_units(
            monkeypatch, f"inkypi-rollback-{launched}.service loaded active running\n"
        )

        data = client.get("/settings/update_status").get_json()

        assert data["running"] is True
        assert data["kind"] == "rollback"

    @pytest.mark.parametrize(
        "stdout",
        [
            "",
            "inkypi.service loaded active running InkyPi\n",
            "inkypi-update-abc.service loaded active running\n",
            "inkypi-update-123.service.evil loaded active running\n",
            f"inkypi-update-{int(time.time()) - 4000}.service loaded active running\n",
        ],
    )
    def test_ignores_other_and_timed_out_units(
        self,
        client: FlaskClient,
        fresh_state: dict[str, object],
        monkeypatch: pytest.MonkeyPatch,
        stdout: str,
    ) -> None:
        self._list_units(monkeypatch, stdout)

        data = client.get("/settings/update_status").get_json()

        assert data["running"] is False
        assert fresh_state["running"] is False

    def test_listing_failure_means_not_running(
        self, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_run(cmd: list[str], *args: Any, **kwargs: Any) -> Any:
            raise FileNotFoundError("systemctl")

        monkeypatch.setattr(updates, "_systemd_available", lambda: True)
        monkeypatch.setattr(subprocess, "run", fake_run)

        assert client.get("/settings/update_status").get_json()["running"] is False

    def test_no_listing_while_a_run_is_recorded(
        self,
        client: FlaskClient,
        fresh_state: dict[str, object],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _mark_running(fresh_state)
        calls = self._list_units(monkeypatch, "")

        client.get("/settings/update_status")

        assert [c[:2] for c in calls] == [["systemctl", "is-active"]]
