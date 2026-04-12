"""Update, update-status, and version-check route handlers."""

import time

from flask import current_app, jsonify, request
from werkzeug.exceptions import BadRequest

import blueprints.settings as _mod
from utils.http_utils import json_error, json_internal_error, json_success


@_mod.settings_bp.route("/settings/update", methods=["POST"])  # start update
def start_update():
    """Trigger InkyPi update via systemd-run when available, with dev fallback.

    Accepts optional JSON body ``{"target_version": "v1.2.0"}`` to update to a
    specific tag.  Returns JSON immediately; progress is visible in the Logs
    panel via /api/logs.
    """
    try:
        # Accept optional target tag from JSON body before acquiring the lock so
        # we can validate it without holding the lock longer than necessary.
        target_tag: str | None = None
        raw_body = request.get_data(cache=True)
        if request.is_json and raw_body.strip():
            try:
                body = request.get_json(silent=False)
            except BadRequest:
                return json_error("Invalid JSON payload", status=400)
            if not isinstance(body, dict):
                return json_error("Request body must be a JSON object", status=400)
        else:
            body = {}

        raw = body.get("target_version")
        if raw and isinstance(raw, str):
            target_tag = raw.strip()

        if target_tag and not _mod._TAG_RE.fullmatch(target_tag):
            return json_error("Invalid target version format", status=400)

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
    except Exception as e:
        _mod.logger.exception("/settings/update error")
        return json_internal_error("start update", details={"error": str(e)})


@_mod.settings_bp.route("/settings/update_status", methods=["GET"])
def update_status():
    try:
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

        return jsonify(
            {
                "running": running,
                "unit": unit,
                "started_at": started_at,
            }
        )
    except Exception as e:
        return json_internal_error("update status", details={"error": str(e)})


@_mod.settings_bp.route("/api/version", methods=["GET"])
def api_version():
    """Return current and latest version info."""
    try:
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
    except Exception as e:
        return json_internal_error("version check", details={"error": str(e)})
