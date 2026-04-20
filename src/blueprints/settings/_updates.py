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


@_mod.settings_bp.route("/settings/update_status", methods=["GET"])
def update_status():
    with route_error_boundary(
        "update status",
        logger=_mod.logger,
        hint="Check systemd status access and last-update metadata files.",
    ):
        import subprocess

        running = bool(_mod._UPDATE_STATE.get("running"))
        unit = _mod._UPDATE_STATE.get("unit")
        started_at = _mod._UPDATE_STATE.get("started_at")

        # Auto-clear stale update state
        if running:
            cleared = False
            # Check if the systemd transient unit has finished
            if unit and _mod._systemd_available():
                try:
                    result = subprocess.run(
                        ["systemctl", "is-active", unit],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    status = result.stdout.strip()
                    if status not in ("active", "activating"):
                        _mod._UPDATE_STATE["last_unit"] = unit
                        _mod._set_update_state(False, None)
                        cleared = True
                except Exception:
                    pass
            # Timeout fallback: force-clear if started >30 min ago
            if (
                not cleared
                and started_at
                and (time.time() - float(started_at)) > _mod._UPDATE_TIMEOUT_SECONDS
            ):
                _mod._UPDATE_STATE["last_unit"] = unit
                _mod._set_update_state(False, None)

            # Re-read after potential clear
            running = bool(_mod._UPDATE_STATE.get("running"))
            unit = _mod._UPDATE_STATE.get("unit")
            started_at = _mod._UPDATE_STATE.get("started_at")

        # JTN-710: surface the last update failure (written by the EXIT trap
        # in install/update.sh) so the UI can show *why* an update failed
        # without the user SSHing in to read the system journal.
        last_failure = read_last_update_failure()

        # JTN-708: surface the prev_version breadcrumb so the UI can gate the
        # "Roll back" button on whether a valid previous tag exists.  The read
        # already applies the strict semver regex, so an unreadable / corrupt
        # file is returned as ``None`` (button stays hidden).
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
