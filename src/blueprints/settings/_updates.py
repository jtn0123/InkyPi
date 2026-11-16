"""Update, rollback, update-status and version-check route handlers.

The update state machine lives in ``services.updates``: these handlers parse
the request, call it, and turn its result into a response.
"""

from flask import Response, current_app, jsonify, request
from werkzeug.exceptions import BadRequest

from blueprints.settings import logger, settings_bp
from services import updates, version_check
from utils.api_responses import JsonResponse, json_error, json_success
from utils.backend_errors import (
    ClientInputError,
    ConflictRouteError,
    route_error_boundary,
)


def _parse_target_version() -> str | None:
    """Return the optional ``target_version`` from the JSON body.

    JTN-710: a ``target_version`` that is present must be a valid tag, so
    ``null`` or ``""`` is refused here instead of silently meaning "latest"
    and failing later in do_update.sh where only the journal shows why.
    """
    raw_body = request.get_data(cache=True)
    if not (request.is_json and raw_body.strip()):
        return None
    try:
        body = request.get_json(silent=False)
    except BadRequest as exc:
        raise ClientInputError("Invalid JSON payload", status=400) from exc
    if not isinstance(body, dict):
        raise ClientInputError("Request body must be a JSON object", status=400)
    if "target_version" not in body:
        return None
    raw = body.get("target_version")
    if raw is None or not isinstance(raw, str) or not raw.strip():
        raise ClientInputError(
            "target_version must be a non-empty string",
            status=400,
            code="validation_error",
            field="target_version",
        )
    target_tag = raw.strip()
    if not updates._TAG_RE.fullmatch(target_tag):
        raise ClientInputError(
            "Invalid target version format",
            status=400,
            code="validation_error",
            field="target_version",
        )
    return target_tag


def _refused(refusal: updates.Refusal, unit: str | None) -> JsonResponse:
    """Answer a refused start with 409 and the reason's code.

    A refusal changed nothing, so a run that is going keeps going. The reply
    to "already running" also carries ``running`` and the run's ``unit``.
    """
    if refusal.code != updates.ALREADY_RUNNING:
        raise ConflictRouteError(refusal.message, status=409, code=refusal.code)
    response, status = json_error(refusal.message, status=409, code=refusal.code)
    payload = response.get_json() if isinstance(response, Response) else response
    body = dict(payload) if isinstance(payload, dict) else {}
    body["running"] = True
    body["unit"] = unit
    return jsonify(body), status


@settings_bp.route("/settings/update", methods=["POST"])
def start_update() -> JsonResponse | Response:
    """Start an InkyPi update (systemd-run on the device, simulated in dev).

    Accepts an optional JSON body ``{"target_version": "v1.2.0"}``. Returns
    at once; the Settings page then follows the run on /settings/update_status.
    """
    with route_error_boundary(
        "start update",
        logger=logger,
        hint="Check update script availability and update process startup.",
    ):
        result = updates.start_update(_parse_target_version())
        if result.refusal is not None:
            return _refused(result.refusal, result.unit)
        return json_success(
            message="Update started. Watch the Logs panel for progress.",
            running=True,
            unit=result.unit,
        )


@settings_bp.route("/settings/update_status", methods=["GET"])
def update_status() -> Response:
    with route_error_boundary(
        "update status",
        logger=logger,
        hint="Check systemd status access and last-update metadata files.",
    ):
        current = updates.status()
        return jsonify(
            {
                "running": current.running,
                "kind": current.kind,
                "unit": current.unit,
                "started_at": current.started_at,
                "last_failure": current.last_failure,
                "prev_version": current.prev_version,
                "rollback_eligible": current.rollback_eligible,
            }
        )


@settings_bp.route("/settings/update/rollback", methods=["POST"])
def start_rollback() -> JsonResponse | Response:
    """Roll back to the tag in ``/var/lib/inkypi/prev_version`` (JTN-708).

    409 unless the last update failed past its pre-flight checks, a valid
    previous version is recorded, and no other run is going (see
    ``services.updates.rollback_eligibility``). A refusal never changes the
    state of a run that is going. 202 when the rollback started.
    """
    with route_error_boundary(
        "start rollback",
        logger=logger,
        hint="Check rollback prerequisites and update runner availability.",
    ):
        result = updates.start_rollback()
        if result.refusal is not None:
            return _refused(result.refusal, result.unit)
        return json_success(
            message=(
                f"Rollback to {result.target_version} started. "
                "Watch the Logs panel for progress."
            ),
            status=202,
            running=True,
            unit=result.unit,
            target_version=result.target_version,
        )


@settings_bp.route("/api/version", methods=["GET"])
def api_version() -> Response:
    """Return current and latest version info.

    Accepts ``?force=1`` to bypass the in-process cache so the "Check for
    updates" button always hits GitHub instead of serving a possibly-stale
    result from an earlier page load. Returns ``check_succeeded`` / ``check_error``
    so the UI can distinguish "you're on latest" from "we couldn't reach GitHub".
    """
    with route_error_boundary(
        "version check",
        logger=logger,
        hint="Check release metadata retrieval and semver parsing.",
    ):
        force_refresh = request.args.get("force", "").lower() in ("1", "true", "yes")
        current = current_app.config.get("APP_VERSION", "unknown")
        latest = version_check._check_latest_version(force_refresh=force_refresh)
        update_available = False
        if latest and current != "unknown":
            update_available = version_check._semver_gt(latest, current)
        check_error = version_check._VERSION_CACHE.get("last_error")
        return jsonify(
            {
                "current": current,
                "latest": latest,
                "update_available": update_available,
                "update_running": updates.is_running(),
                "release_notes": version_check._VERSION_CACHE.get("release_notes"),
                "check_succeeded": latest is not None,
                "check_error": check_error if latest is None else None,
            }
        )
