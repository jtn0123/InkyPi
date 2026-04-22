"""Update, update-status, and version-check route handlers."""

import os
import time

from flask import current_app, jsonify, request
from werkzeug.exceptions import BadRequest

import blueprints.settings as _mod
from blueprints.settings._update_status import read_last_update_failure
from utils.backend_errors import (
    ClientInputError,
    ConflictRouteError,
    route_error_boundary,
)
from utils.http_utils import json_error, json_success


def _prev_version_path() -> str:
    """Resolve the prev_version breadcrumb path (JTN-673 / JTN-708).

    Honors ``INKYPI_LOCKFILE_DIR`` so integration tests can redirect state
    writes to a tempdir — same contract as ``_update_status.py`` uses for
    ``.last-update-failure``.
    """
    base = os.environ.get("INKYPI_LOCKFILE_DIR") or "/var/lib/inkypi"
    return os.path.join(base, "prev_version")


def _read_prev_version() -> str | None:
    """Return the tag recorded in ``/var/lib/inkypi/prev_version`` or ``None``.

    Applies the same strict semver regex as ``_TAG_RE`` to refuse malformed
    records — defense-in-depth for the UI: if the file got corrupted we
    simply hide the rollback button rather than advertising an unusable
    target.
    """
    try:
        with open(_prev_version_path(), encoding="utf-8") as fh:
            raw = fh.read().strip()
    except OSError:
        return None
    if not raw or not _mod._TAG_RE.fullmatch(raw):
        return None
    return raw


@_mod.settings_bp.route("/settings/update", methods=["POST"])  # start update
def start_update():
    """Trigger InkyPi update via systemd-run when available, with dev fallback.

    Accepts optional JSON body ``{"target_version": "v1.2.0"}`` to update to a
    specific tag.  Returns JSON immediately; progress is visible in the Logs
    panel via /api/logs.
    """
    with route_error_boundary(
        "start update",
        logger=_mod.logger,
        hint="Check update script availability and update process startup.",
    ):
        # JTN-K3: If a prior update exited before the lockfile/trap machinery
        # could clear ``_UPDATE_STATE["running"]`` (e.g. do_update.sh bailed
        # during pre-checkout validation), the stale flag permanently blocks
        # new updates with 409 until someone happens to hit GET
        # /settings/update_status — which is the only place that ran the
        # reaper.  Run the same reaper here so POST self-heals instead of
        # forcing a manual GET first.
        _auto_clear_stale_update_state()
        # Accept optional target tag from JSON body before acquiring the lock so
        # we can validate it without holding the lock longer than necessary.
        target_tag: str | None = None
        raw_body = request.get_data(cache=True)
        if request.is_json and raw_body.strip():
            try:
                body = request.get_json(silent=False)
            except BadRequest as exc:
                raise ClientInputError("Invalid JSON payload", status=400) from exc
            if not isinstance(body, dict):
                raise ClientInputError("Request body must be a JSON object", status=400)
        else:
            body = {}

        # JTN-710: if ``target_version`` is present in the body, validate
        # it explicitly instead of silently falling through to the
        # "latest semver tag" code path when it's null/empty.  Without this
        # guard, a client sending ``{"target_version": null}`` or
        # ``{"target_version": ""}`` caused do_update.sh to fail with
        # "No semver tags found" only visible in the system journal.
        if "target_version" in body:
            raw = body.get("target_version")
            if raw is None or not isinstance(raw, str) or not raw.strip():
                raise ClientInputError(
                    "target_version must be a non-empty string",
                    status=400,
                    code="validation_error",
                    field="target_version",
                )
            target_tag = raw.strip()
            if not _mod._TAG_RE.fullmatch(target_tag):
                raise ClientInputError(
                    "Invalid target version format",
                    status=400,
                    code="validation_error",
                    field="target_version",
                )

        script_path = _mod._get_update_script_path()
        # NOTE: the systemd unit name is now generated *inside*
        # ``_start_update_via_systemd`` from a hardcoded literal prefix.
        # We still mirror the same prefix here for the running-state breadcrumb
        # surfaced via /settings/update_status — the value below is purely an
        # in-process state hint and is never passed to subprocess.Popen.
        unit = f"inkypi-update-{int(time.time())}"
        use_systemd = _mod._systemd_available()

        # Atomically check-and-set the running flag so concurrent requests
        # cannot both pass the guard (TOCTOU fix: the check and the state flip
        # happen inside the same lock acquisition).
        #
        # NOTE: _set_update_state() also acquires _update_lock, so we inline
        # the state mutation here to avoid re-entering the non-reentrant lock.
        with _mod._update_lock:
            if _mod._UPDATE_STATE.get("running"):
                # NOTE: ``running`` and ``unit`` are kept at the top level for
                # backward compatibility with existing clients and tests.
                response, _ = json_error("Update already in progress.", status=409)
                payload = response.get_json()
                payload["running"] = True
                payload["unit"] = _mod._UPDATE_STATE.get("unit")
                return jsonify(payload), 409
            # Flip the state while still holding the lock (inlined to avoid
            # re-acquiring the non-reentrant lock inside _set_update_state).
            new_unit = f"{unit}.service" if use_systemd else None
            _mod._UPDATE_STATE["running"] = True
            _mod._UPDATE_STATE["unit"] = new_unit
            _mod._UPDATE_STATE["started_at"] = float(time.time())

        # Start the actual update process outside the lock (I/O-heavy, must not
        # block other threads that only need a brief lock).
        if use_systemd:
            try:
                # JTN-319: ``_start_update_via_systemd`` no longer accepts an
                # external script path or unit name — both are derived from
                # hardcoded constants inside the function so CodeQL can prove
                # the Popen argv is not user-influenced.
                _mod._start_update_via_systemd(target_tag=target_tag)
            except Exception:
                # If systemd-run fails unexpectedly, fall back to thread runner
                _mod.logger.exception(
                    "systemd-run failed; falling back to thread runner"
                )
                _mod._start_update_fallback_thread(script_path, target_tag=target_tag)
        else:
            _mod._start_update_fallback_thread(script_path, target_tag=target_tag)

        return json_success(
            message="Update started. Watch the Logs panel for progress.",
            running=True,
            unit=_mod._UPDATE_STATE.get("unit"),
        )


def _probe_finished_unit(unit: str) -> tuple[bool, bool]:
    """Return ``(cleared, unit_was_failed)`` for the systemd transient unit.

    ``cleared`` is True if the unit has reached a terminal state (anything
    other than ``active``/``activating``) so the caller should flip running
    to False. ``unit_was_failed`` is True only when systemd reports
    ``failed`` — used by JTN-787 to decide whether to synthesize a
    last_failure from the journal.

    All exceptions swallowed — status probing must never fail the endpoint.
    """
    import subprocess

    try:
        result = subprocess.run(
            ["systemctl", "is-active", unit],
            capture_output=True,
            text=True,
            timeout=5,
        )
        status = result.stdout.strip()
        if status in ("active", "activating"):
            return (False, False)
        return (True, status == "failed")
    except Exception:
        return (False, False)


def _synthesize_failure_from_journal(unit: str) -> dict[str, object] | None:
    """JTN-787: build a last_failure record from ``journalctl -u <unit>``.

    Returns ``None`` when journalctl is unavailable, the unit has no
    journal lines, or anything else goes wrong. The returned shape mirrors
    the JTN-704 trap-written record plus a ``synthesized: True`` marker so
    UI consumers can distinguish the two origins.
    """
    import datetime as _dt
    import subprocess

    try:
        journal_result = subprocess.run(
            ["journalctl", "-u", unit, "-n", "20", "--no-pager"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        _mod.logger.debug(
            "Failed to synthesize last_failure from journalctl", exc_info=True
        )
        return None
    journal_tail = (journal_result.stdout or "").strip()
    if not journal_tail:
        return None
    return {
        "timestamp": _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "exit_code": None,
        "last_command": "systemd_unit_failed",
        "recent_journal_lines": journal_tail,
        "unit": unit,
        "synthesized": True,
    }


def _auto_clear_stale_update_state() -> tuple[str | None, bool]:
    """Clear ``_UPDATE_STATE`` when the transient systemd unit has finished.

    Extracted from ``update_status`` so the endpoint stays under the
    15-point cognitive-complexity cap (JTN-787 / SonarCloud S3776).

    Returns ``(failed_unit_name, unit_failed)`` — ``failed_unit_name`` is
    the unit whose completion triggered the clear, returned ONLY when the
    unit ended in ``failed`` state (for the journal-synthesis fallback).
    ``None`` when nothing needed clearing or the unit succeeded.

    JTN-K3: the clear is compare-and-clear under ``_update_lock`` — the
    slow ``systemctl is-active`` probe happens outside the lock, but the
    final mutation only fires if ``(running, unit, started_at)`` still
    matches the snapshot we probed against.  Without this guard, two POSTs
    to /settings/update can race: request A reads stale state and calls
    the reaper, request B acquires the lock and starts a fresh update
    between A's probe and A's clear, then A's clear erases B's freshly-set
    running flag and the guard lets a third request start a second update.
    """
    if not _mod._UPDATE_STATE.get("running"):
        return None, False

    unit = _mod._UPDATE_STATE.get("unit")
    started_at = _mod._UPDATE_STATE.get("started_at")
    failed_name: str | None = None
    unit_failed = False

    cleared = False
    if unit and _mod._systemd_available():
        cleared, unit_failed = _probe_finished_unit(unit)
        if cleared:
            with _mod._update_lock:
                # Compare-and-clear: only clear if the state we probed is
                # still the current state.  Otherwise a concurrent POST
                # already started a new update and must not be disturbed.
                if (
                    _mod._UPDATE_STATE.get("running")
                    and _mod._UPDATE_STATE.get("unit") == unit
                    and _mod._UPDATE_STATE.get("started_at") == started_at
                ):
                    _mod._UPDATE_STATE["last_unit"] = unit
                    _mod._UPDATE_STATE["running"] = False
                    _mod._UPDATE_STATE["unit"] = None
                    _mod._UPDATE_STATE["started_at"] = None
                    if unit_failed:
                        failed_name = unit
                else:
                    # A newer update replaced the state we snapshotted;
                    # the reaper must not clear it.
                    cleared = False

    # Timeout fallback: force-clear if started >30 min ago.  Same
    # compare-and-clear discipline so we never stomp on a fresh start.
    if (
        not cleared
        and started_at
        and (time.time() - float(started_at)) > _mod._UPDATE_TIMEOUT_SECONDS
    ):
        with _mod._update_lock:
            if (
                _mod._UPDATE_STATE.get("running")
                and _mod._UPDATE_STATE.get("unit") == unit
                and _mod._UPDATE_STATE.get("started_at") == started_at
            ):
                _mod._UPDATE_STATE["last_unit"] = unit
                _mod._UPDATE_STATE["running"] = False
                _mod._UPDATE_STATE["unit"] = None
                _mod._UPDATE_STATE["started_at"] = None

    return failed_name, unit_failed


@_mod.settings_bp.route("/settings/update_status", methods=["GET"])
def update_status():
    with route_error_boundary(
        "update status",
        logger=_mod.logger,
        hint="Check systemd status access and last-update metadata files.",
    ):
        failed_unit_name, _unit_failed = _auto_clear_stale_update_state()

        running = bool(_mod._UPDATE_STATE.get("running"))
        unit = _mod._UPDATE_STATE.get("unit")
        started_at = _mod._UPDATE_STATE.get("started_at")

        # JTN-710: surface the last update failure (written by the EXIT trap
        # in install/update.sh) so the UI can show *why* an update failed
        # without the user SSHing in to read the system journal.
        last_failure = read_last_update_failure()

        # JTN-787: If the transient systemd unit transitioned to ``failed``
        # but no ``.last-update-failure`` file was written, synthesize one
        # from the unit's journal tail. This covers the case where
        # ``install/do_update.sh`` aborts before delegating to
        # ``install/update.sh`` (e.g. a dirty working tree blocks
        # ``git checkout``) on a pre-JTN-787 installed script.
        if last_failure is None and failed_unit_name:
            synthesized = _synthesize_failure_from_journal(failed_unit_name)
            if synthesized is not None:
                last_failure = synthesized

        # JTN-708: surface the prev_version breadcrumb so the UI can gate the
        # "Roll back" button on whether a valid previous tag exists.
        prev_version = _read_prev_version()

        return jsonify(
            {
                "running": running,
                "unit": unit,
                "started_at": started_at,
                "last_failure": last_failure,
                "prev_version": prev_version,
            }
        )


@_mod.settings_bp.route("/settings/update/rollback", methods=["POST"])
def start_rollback():
    """Trigger a rollback to the tag recorded in ``/var/lib/inkypi/prev_version``.

    JTN-708: completes the failed-update recovery loop.

    Gating rules (return 409 otherwise):
        * ``.last-update-failure`` must exist — rollback is an emergency
          recovery path, not a "time machine". If the current install is
          healthy, use /settings/update with an explicit target_version.
        * ``prev_version`` must exist AND match the strict semver regex.  A
          corrupt/missing breadcrumb means we have no safe target.
        * No other update may be running (409 matches the /settings/update
          TOCTOU guard).

    The heavy lifting is in ``install/rollback.sh``: it reads the breadcrumb,
    checks out the tag, then exec's ``update.sh`` — so the EXIT trap
    (JTN-704) still records failures to ``.last-update-failure`` if the
    rollback itself fails.
    """
    try:
        with route_error_boundary(
            "start rollback",
            logger=_mod.logger,
            hint="Check rollback prerequisites and update runner availability.",
        ):
            # 1. Require a recorded last-update-failure.  Without one, a rollback
            #    would be reverting a healthy install — refuse.
            last_failure = read_last_update_failure()
            if not last_failure:
                raise ConflictRouteError(
                    "No failed update recorded; nothing to roll back.",
                    status=409,
                    code="no_failure",
                )

            # 2. Require a validated prev_version breadcrumb.
            prev_version = _read_prev_version()
            if not prev_version:
                raise ConflictRouteError(
                    "No previous version recorded; cannot roll back.",
                    status=409,
                    code="no_prev_version",
                )

            use_systemd = _mod._systemd_available()
            unit = f"inkypi-rollback-{int(time.time())}"

            # 3. TOCTOU-safe check-and-set — mirror start_update's pattern so two
            #    concurrent rollback clicks can't both pass the guard.
            with _mod._update_lock:
                if _mod._UPDATE_STATE.get("running"):
                    response, _ = json_error(
                        "Update or rollback already in progress.", status=409
                    )
                    payload = response.get_json()
                    payload["running"] = True
                    payload["unit"] = _mod._UPDATE_STATE.get("unit")
                    return jsonify(payload), 409
                new_unit = f"{unit}.service" if use_systemd else None
                _mod._UPDATE_STATE["running"] = True
                _mod._UPDATE_STATE["unit"] = new_unit
                _mod._UPDATE_STATE["started_at"] = float(time.time())

            if use_systemd:
                try:
                    _mod._start_rollback_via_systemd()
                except Exception:
                    _mod.logger.exception(
                        "systemd-run failed for rollback; clearing running state"
                    )
                    _mod._set_update_state(False, None)
                    raise
            else:
                # Dev / macOS path: reuse the simulated update runner so the UI
                # still sees log output.  Production Pi always has systemd.
                _mod._start_update_fallback_thread(None, target_tag=prev_version)

            # JTN-708: 202 Accepted lets clients/tests distinguish "rollback
            # kicked off" from a synchronous reply; the UI polls
            # /settings/update_status for completion.
            return json_success(
                message=(
                    f"Rollback to {prev_version} started. "
                    "Watch the Logs panel for progress."
                ),
                status=202,
                running=True,
                unit=_mod._UPDATE_STATE.get("unit"),
                target_version=prev_version,
            )
    except Exception:
        _mod._set_update_state(False, None)
        raise


@_mod.settings_bp.route("/api/version", methods=["GET"])
def api_version():
    """Return current and latest version info."""
    with route_error_boundary(
        "version check",
        logger=_mod.logger,
        hint="Check release metadata retrieval and semver parsing.",
    ):
        current = current_app.config.get("APP_VERSION", "unknown")
        latest = _mod._check_latest_version()
        update_available = False
        if latest and current != "unknown":
            update_available = _mod._semver_gt(latest, current)
        return jsonify(
            {
                "current": current,
                "latest": latest,
                "update_available": update_available,
                "update_running": bool(_mod._UPDATE_STATE.get("running")),
                "release_notes": _mod._VERSION_CACHE.get("release_notes"),
            }
        )
