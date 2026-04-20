import json
import logging
import os
from time import perf_counter

from flask import (
    Blueprint,
    abort,
    current_app,
    jsonify,
    make_response,
    render_template,
    request,
    send_file,
    send_from_directory,
)

from plugins.plugin_registry import get_plugin_instance
from refresh_task import ManualRefresh, PlaylistRefresh
from refresh_task.job_queue import get_job_queue
from services.plugin_workflows import save_plugin_settings_workflow
from utils.app_utils import handle_request_files, parse_form, resolve_path
from utils.backend_errors import (
    ClientInputError,
    ResourceLookupError,
    UnsupportedMediaTypeRouteError,
    route_error_boundary,
)
from utils.fallback_image import render_error_image
from utils.form_utils import (
    sanitize_log_field,
    validate_plugin_required_fields,
)
from utils.http_utils import json_error, json_success
from utils.messages import PLAYLIST_NAME_REQUIRED_ERROR
from utils.plugin_history import record_change as _record_plugin_change
from utils.progress import track_progress
from utils.security_utils import URLValidationError, validate_file_path

logger = logging.getLogger(__name__)
plugin_bp = Blueprint("plugin", __name__)

# Sonar S1192 — duplicate string constants
_CONFIG_KEY = "DEVICE_CONFIG"
_PLUGIN_ID = "plugin_id"
_ERR_INTERNAL = "An internal error occurred"
_ERR_NOT_FOUND = "Not Found"
_MSG_DISPLAY_UPDATED = "Display updated"
_ERR_PLUGIN_ID_REQUIRED = "plugin_id is required"
_ERR_PLUGIN_INSTANCE_NOT_FOUND = "Plugin instance not found"
_ERR_PLUGIN_NOT_FOUND = "Plugin not found"
_ERR_PLAYLIST_NOT_FOUND = "Playlist not found"
_MSG_CIRCUIT_BREAKER_RESET = "Circuit-breaker reset for plugin instance."


def _plugins_dir() -> str:
    """Resolve the current plugin source directory at request time."""
    return resolve_path("plugins")


def _cacheable_send_file(path: str, ttl_env: str = "INKYPI_RENDER_CACHE_TTL_S"):
    safe_path = os.path.realpath(path)
    if not os.path.isfile(safe_path):
        abort(404)
    resp = send_file(safe_path)
    try:
        ttl = int(os.getenv(ttl_env, "300") or "300")
    except Exception:
        ttl = 300
    ttl = max(0, ttl)
    resp.headers["Cache-Control"] = f"public, max-age={ttl}"
    basename = os.path.basename(safe_path)
    resp.headers["Content-Disposition"] = f'inline; filename="{basename}"'
    return resp


@plugin_bp.route("/plugin/<plugin_id>", methods=["GET"])
def plugin_page(plugin_id: str):
    device_config = current_app.config[_CONFIG_KEY]
    playlist_manager = device_config.get_playlist_manager()

    plugin_config = device_config.get_plugin(plugin_id)
    if not plugin_config:
        abort(404)

    with route_error_boundary(
        "render plugin page",
        logger=logger,
        hint="Check plugin configuration and template generation.",
    ):
        plugin = get_plugin_instance(plugin_config)
        template_params = plugin.generate_settings_template()

        # Check if API key is present for plugins that require it
        if "api_key" in template_params and template_params["api_key"].get("required"):
            expected_key = template_params["api_key"].get("expected_key")
            if expected_key:
                key_present = device_config.load_env_key(expected_key) is not None
                template_params["api_key"]["present"] = key_present

        # If viewing an existing instance, pre-populate its settings
        plugin_instance_name = request.args.get("instance")
        if plugin_instance_name:
            plugin_instance = playlist_manager.find_plugin(
                plugin_id, plugin_instance_name
            )
            if not plugin_instance:
                logger.warning(
                    "Plugin instance lookup failed: plugin_id=%s instance=%s",
                    sanitize_log_field(plugin_id),
                    sanitize_log_field(plugin_instance_name),
                )
                raise ResourceLookupError(
                    _ERR_PLUGIN_INSTANCE_NOT_FOUND,
                    status=404,
                )
            template_params["plugin_settings"] = plugin_instance.settings
            template_params["plugin_instance"] = plugin_instance_name
        else:
            # Try to pre-populate from a saved settings instance on Default playlist
            default_playlist = playlist_manager.get_playlist("Default")
            if default_playlist:
                saved_instance_name = f"{plugin_id}_saved_settings"
                saved_instance = default_playlist.find_plugin(
                    plugin_id, saved_instance_name
                )
                if saved_instance:
                    template_params["plugin_settings"] = saved_instance.settings
                    template_params["plugin_instance"] = saved_instance_name

        template_params["playlists"] = playlist_manager.get_playlist_names()

        # Find latest refresh time for this plugin (any instance)
        plugin_latest_refresh = _find_latest_plugin_refresh_time(
            device_config, plugin_id
        )
        if plugin_latest_refresh:
            template_params["plugin_latest_refresh"] = plugin_latest_refresh

    return render_template(
        "plugin.html",
        plugin=plugin_config,
        resolution=device_config.get_resolution(),
        config=device_config.get_config(),
        **template_params,
    )


@plugin_bp.route("/images/<plugin_id>/<path:filename>", methods=["GET"])
def image(plugin_id: str, filename: str):
    # Reject null-byte / absolute path inputs up front (defence in depth).
    if (
        not plugin_id
        or "\x00" in plugin_id
        or "\x00" in filename
        or os.path.isabs(filename)
        or os.path.isabs(plugin_id)
        or plugin_id in (".", "..")
    ):
        abort(404)

    # Resolve every path segment by scanning a server-owned directory with
    # os.listdir() and matching against the user-supplied string.  The
    # eventual path passed to send_from_directory is built entirely from
    # os.listdir() output, not from request input, which keeps CodeQL's
    # py/path-injection taint flow from reaching the filesystem call.
    segments = [s for s in filename.replace("\\", "/").split("/") if s]
    if not segments or any(s in (".", "..") for s in segments):
        abort(404)

    def _match_listdir(directory: str, wanted: str) -> str | None:
        try:
            entries = os.listdir(directory)
        except OSError:
            return None
        for entry in entries:
            if entry == wanted:
                return entry  # returned value is from os.listdir, not user input
        return None

    plugins_dir = _plugins_dir()

    # Resolve plugin_id against the current plugin source tree.
    plugin_dirname = _match_listdir(plugins_dir, plugin_id)
    if plugin_dirname is None:
        logger.warning(
            "plugin.image: unknown plugin_id=%s",
            sanitize_log_field(plugin_id),
        )
        abort(404)

    # Build the directory path from the listdir-derived name.
    cursor = os.path.join(plugins_dir, plugin_dirname)
    resolved_parts: list[str] = []
    for segment in segments:
        match = _match_listdir(cursor, segment)
        if match is None:
            abort(404)
        resolved_parts.append(match)
        cursor = os.path.join(cursor, match)

    # Defence-in-depth: reject any symlink entry that escapes PLUGINS_DIR.
    try:
        validate_file_path(cursor, plugins_dir)
    except ValueError:
        abort(404)

    if not os.path.isfile(cursor):
        abort(404)

    safe_dir = os.path.join(plugins_dir, plugin_dirname)
    safe_name = os.path.join(*resolved_parts)
    resp = send_from_directory(safe_dir, safe_name)
    try:
        ttl = int(os.getenv("INKYPI_STATIC_PLUGIN_ASSET_TTL_S", "300") or "300")
    except Exception:
        ttl = 300
    resp.headers["Cache-Control"] = f"public, max-age={max(0, ttl)}"
    resp.headers["Content-Disposition"] = f'inline; filename="{resolved_parts[-1]}"'
    return resp


@plugin_bp.route(
    "/plugin_latest_image/<string:plugin_id>",
    endpoint="plugin_latest_image",
    methods=["GET"],
)
def latest_plugin_image(plugin_id: str):
    """Serve the most recent history image for a given plugin_id.

    Searches the history directory for the latest PNG matching the plugin_id,
    regardless of instance name. Used by the plugin page to show "Latest from this plugin".

    JSON files are sorted by filename descending (newest first) so the first
    match is the most recent, giving O(1) reads in the common case.
    """
    device_config = current_app.config[_CONFIG_KEY]
    try:
        history_dir = str(device_config.history_image_dir)
        if not os.path.isdir(history_dir):
            return (_ERR_NOT_FOUND, 404)

        # Pre-filter to .json files and sort newest-first by filename
        json_files = sorted(
            (n for n in os.listdir(history_dir) if n.endswith(".json")),
            reverse=True,
        )

        for name in json_files:
            json_path = os.path.join(history_dir, name)
            try:
                with open(json_path, encoding="utf-8") as fh:
                    meta = json.load(fh)
                if meta.get(_PLUGIN_ID) == plugin_id:
                    png_path = os.path.join(history_dir, name.replace(".json", ".png"))
                    if os.path.exists(png_path):
                        return _cacheable_send_file(png_path)
            except Exception:
                continue

        return (_ERR_NOT_FOUND, 404)

    except Exception:
        return (_ERR_NOT_FOUND, 404)


def _cleanup_plugin_resources(
    device_config, plugin_id, plugin_instance_name, plugin_settings=None
) -> None:
    """Clean up cached image and run plugin-specific teardown after instance deletion.

    Both cleanup steps are best-effort: failures are logged as warnings but do not
    propagate so the caller's success response is unaffected.

    ``plugin_settings`` should be the deleted instance's settings dict so that
    plugin-specific cleanup (e.g. image_upload removing uploaded files) can
    inspect its own configuration.
    """
    # Clean up cached plugin instance image
    try:
        image_path = device_config.get_plugin_image_path(
            plugin_id, plugin_instance_name
        )
        if image_path and os.path.isfile(image_path):
            os.remove(image_path)
            logger.info("Removed cached image: %s", image_path)
    except Exception:
        logger.warning(
            "Could not clean up image for %s/%s",
            sanitize_log_field(plugin_id),
            sanitize_log_field(str(plugin_instance_name)),
            exc_info=True,
        )

    # Run plugin-specific cleanup (e.g., image_upload deletes uploaded files)
    try:
        plugin_config = device_config.get_plugin(plugin_id)
        if plugin_config:
            plugin_obj = get_plugin_instance(plugin_config)
            if plugin_obj and hasattr(plugin_obj, "cleanup"):
                plugin_obj.cleanup(plugin_settings or {})
    except Exception:
        logger.warning(
            "Plugin cleanup failed for %s", sanitize_log_field(plugin_id), exc_info=True
        )


@plugin_bp.route("/delete_plugin_instance", methods=["POST", "DELETE"])
def delete_plugin_instance():
    device_config = current_app.config[_CONFIG_KEY]
    playlist_manager = device_config.get_playlist_manager()

    if not request.is_json:
        raise UnsupportedMediaTypeRouteError
    data = request.json or {}

    playlist_name = data.get("playlist_name")
    plugin_id = data.get(_PLUGIN_ID)
    plugin_instance = data.get("plugin_instance")

    if (
        not playlist_name
        or not isinstance(playlist_name, str)
        or not playlist_name.strip()
    ):
        raise ClientInputError(PLAYLIST_NAME_REQUIRED_ERROR, status=400)
    playlist_name = playlist_name.strip()

    with route_error_boundary(
        "delete plugin instance",
        logger=logger,
        hint="Ensure the playlist and plugin instance exist before deleting.",
    ):
        playlist = playlist_manager.get_playlist(playlist_name)
        if not playlist:
            raise ResourceLookupError("Playlist not found", status=400)

        existing = playlist.find_plugin(plugin_id, plugin_instance)
        plugin_settings = dict(existing.settings) if existing else {}

        del_result: list[bool] = []

        def _do_delete(cfg):
            del_result.append(playlist.delete_plugin(plugin_id, plugin_instance))

        device_config.update_atomic(_do_delete)
        if not del_result or not del_result[0]:
            raise ResourceLookupError("Plugin instance not found", status=400)
        _cleanup_plugin_resources(
            device_config, plugin_id, plugin_instance, plugin_settings
        )

    return json_success(message="Deleted plugin instance.")


@plugin_bp.route("/update_plugin_instance/<string:instance_name>", methods=["PUT"])
def update_plugin_instance(instance_name: str):
    device_config = current_app.config[_CONFIG_KEY]
    playlist_manager = device_config.get_playlist_manager()

    with route_error_boundary(
        "update plugin instance",
        logger=logger,
        hint="Check submitted plugin settings and config persistence.",
    ):
        form_data = parse_form(request.form)
        if not instance_name:
            raise ClientInputError(
                "Instance name is required",
                status=422,
                code="validation_error",
                field="instance_name",
            )
        plugin_settings = form_data
        plugin_settings.update(handle_request_files(request.files, request.form))

        plugin_id = plugin_settings.pop(_PLUGIN_ID, None)
        if not plugin_id:
            raise ClientInputError(
                _ERR_PLUGIN_ID_REQUIRED,
                status=422,
                code="validation_error",
                field=_PLUGIN_ID,
            )
        plugin_instance = playlist_manager.find_plugin(plugin_id, instance_name)
        if not plugin_instance:
            logger.warning(
                "update_instance: plugin instance not found plugin_id=%s instance=%s",
                sanitize_log_field(plugin_id),
                sanitize_log_field(instance_name),
            )
            raise ResourceLookupError(
                _ERR_PLUGIN_INSTANCE_NOT_FOUND,
                status=404,
            )

        # JTN-381: parse and validate refresh_settings if present. The frontend
        # Refresh Settings modal posts this as a JSON-stringified form field;
        # previously it was accepted blindly, saved into settings verbatim,
        # and the new refresh config was never applied — reload silently
        # reverted the user's change while the toast said "success".
        new_refresh_config = None
        raw_refresh = plugin_settings.pop("refresh_settings", None)
        if raw_refresh is not None:
            try:
                refresh_payload = json.loads(raw_refresh)
            except (TypeError, ValueError) as exc:
                raise ClientInputError(
                    "Refresh settings must be valid JSON",
                    status=400,
                    code="validation_error",
                    field="refresh_settings",
                ) from exc
            if not isinstance(refresh_payload, dict):
                raise ClientInputError(
                    "Refresh settings must be an object",
                    status=400,
                    code="validation_error",
                    field="refresh_settings",
                )
            from blueprints.playlist import validate_plugin_refresh_settings

            new_refresh_config, refresh_err = validate_plugin_refresh_settings(
                refresh_payload
            )
            if refresh_err:
                return refresh_err

        # Validate required fields and plugin-specific settings
        plugin_config = device_config.get_plugin(plugin_id)
        if plugin_config:
            try:
                plugin = get_plugin_instance(plugin_config)
            except Exception:
                logger.warning(
                    "Could not load plugin for validation: %s",
                    sanitize_log_field(plugin_id),
                )
                plugin = None

            if plugin is not None:
                try:
                    validation_error = validate_plugin_required_fields(
                        plugin, plugin_settings
                    )
                except Exception:
                    logger.warning(
                        "Required-field validation failed for %s",
                        sanitize_log_field(plugin_id),
                        exc_info=True,
                    )
                else:
                    if validation_error:
                        raise ClientInputError(validation_error, status=400)

                try:
                    settings_error = plugin.validate_settings(plugin_settings)
                except Exception as exc:
                    logger.warning(
                        "Plugin validate_settings raised for %s",
                        sanitize_log_field(plugin_id),
                        exc_info=True,
                    )
                    raise ClientInputError(
                        "Settings validation failed. Please check your input.",
                        status=400,
                    ) from exc
                else:
                    if settings_error:
                        raise ClientInputError(settings_error, status=400)

        before_settings = dict(plugin_instance.settings or {})

        def _do_update_instance(cfg):
            plugin_instance.settings = plugin_settings
            if new_refresh_config is not None:
                plugin_instance.refresh = new_refresh_config

        device_config.update_atomic(_do_update_instance)
        config_dir = os.path.dirname(device_config.config_file)
        _record_plugin_change(
            config_dir, instance_name, before_settings, plugin_settings
        )

    return json_success(message=f"Updated plugin instance {instance_name}.")


@plugin_bp.route("/display_plugin_instance", methods=["POST"])
def display_plugin_instance():
    device_config = current_app.config[_CONFIG_KEY]
    refresh_task = current_app.config["REFRESH_TASK"]
    playlist_manager = device_config.get_playlist_manager()

    if not request.is_json:
        raise UnsupportedMediaTypeRouteError
    data = request.json or {}

    playlist_name = data.get("playlist_name")
    plugin_id = data.get(_PLUGIN_ID)
    plugin_instance_name = data.get("plugin_instance")

    with route_error_boundary(
        "display plugin instance",
        logger=logger,
        hint="Ensure the playlist exists and the refresh task can run the instance.",
    ):
        playlist = playlist_manager.get_playlist(playlist_name)
        if not playlist:
            logger.warning(
                "display_plugin_instance: playlist not found name=%s",
                sanitize_log_field(playlist_name),
            )
            raise ResourceLookupError(_ERR_PLAYLIST_NOT_FOUND, status=400)

        plugin_instance = playlist.find_plugin(plugin_id, plugin_instance_name)
        if not plugin_instance:
            logger.warning(
                "display_plugin_instance: plugin instance not found "
                "playlist=%s plugin_id=%s instance=%s",
                sanitize_log_field(playlist_name),
                sanitize_log_field(plugin_id),
                sanitize_log_field(plugin_instance_name),
            )
            raise ResourceLookupError(
                _ERR_PLUGIN_INSTANCE_NOT_FOUND,
                status=400,
            )

        refresh_task.manual_update(
            PlaylistRefresh(playlist, plugin_instance, force=True)
        )

    return json_success(message=_MSG_DISPLAY_UPDATED)


@plugin_bp.route(
    "/plugin_instance/<string:plugin_id>/<string:instance_name>/force_retry",
    methods=["POST"],
)
def force_retry_plugin_instance(plugin_id: str, instance_name: str):
    """Clear the circuit-breaker paused state for a plugin instance.

    Allows a paused plugin to be retried on the next scheduler cycle without
    waiting for a successful refresh to reset it automatically.
    """
    refresh_task = current_app.config.get("REFRESH_TASK")
    if refresh_task is None:
        return json_error("Refresh task not available", status=503)
    if not hasattr(refresh_task, "reset_circuit_breaker"):
        return json_error("Circuit-breaker reset not supported", status=501)
    found = refresh_task.reset_circuit_breaker(plugin_id, instance_name)
    if not found:
        logger.warning(
            "force_retry: plugin instance not found plugin_id=%s instance=%s",
            sanitize_log_field(plugin_id),
            sanitize_log_field(instance_name),
        )
        return json_error(
            _ERR_PLUGIN_INSTANCE_NOT_FOUND,
            status=404,
        )
    logger.info(
        "Circuit-breaker reset for plugin_id=%s instance=%s",
        sanitize_log_field(plugin_id),
        sanitize_log_field(instance_name),
    )
    return json_success(
        message=_MSG_CIRCUIT_BREAKER_RESET,
    )


def _safe_display_image(display_manager, image, image_settings, history_meta):
    """Invoke display_manager.display_image, tolerating older stubs without ``history_meta``.

    Some test doubles monkeypatch ``display_image`` with a (image, image_settings)
    signature.  We prefer to pass ``history_meta`` so the history sidecar records
    the plugin_id — without it, /plugin_latest_image/<plugin_id> cannot find the
    image and the "Latest from this plugin" card stays empty (JTN-341).
    """
    try:
        return display_manager.display_image(
            image, image_settings=image_settings, history_meta=history_meta
        )
    except TypeError:
        # Legacy/test stub without the history_meta kwarg
        return display_manager.display_image(image, image_settings=image_settings)


def _update_now_direct(plugin_id, plugin_settings, device_config, display_manager):
    """Execute a plugin directly (refresh task not running) and push to display.

    Returns a Flask response tuple.  On plugin failure, a fallback error-card
    image is pushed to the display before the error response is returned so the
    screen does not stay frozen on stale content.
    """
    plugin_config = device_config.get_plugin(plugin_id)
    if not plugin_config:
        logger.warning(
            "_update_now_direct: plugin not found plugin_id=%s",
            sanitize_log_field(plugin_id),
        )
        return json_error(_ERR_PLUGIN_NOT_FOUND, status=404)

    plugin = get_plugin_instance(plugin_config)
    with track_progress() as tracker:
        _t_req_start = perf_counter()
        _t_gen_start = perf_counter()
        try:
            image = plugin.generate_image(plugin_settings, device_config)
        except URLValidationError as e:
            # JTN-776: URL validation failures are user errors, not server
            # errors. ``safe_message()`` returns a response string looked up
            # from the module-level whitelist in :mod:`utils.security_utils`,
            # which avoids any exception-derived text flowing to the client
            # (CodeQL ``py/stack-trace-exposure``).
            safe_msg = e.safe_message()
            logger.info(
                "Plugin %s rejected URL: %s",
                sanitize_log_field(plugin_id),
                sanitize_log_field(safe_msg),
            )
            _push_update_now_fallback(
                plugin_id, plugin_config, device_config, display_manager, e
            )
            return json_error(
                safe_msg,
                status=422,
                code="validation_error",
                details={"field": "url"},
            )
        except RuntimeError as e:
            # RuntimeError is raised by plugins to signal a user-actionable
            # failure (bad config, upstream API returned empty, etc.).  Do not
            # echo the exception text to the client — CodeQL
            # py/stack-trace-exposure, and plugin messages can occasionally
            # embed tainted fragments.  Log the details server-side (JTN-326).
            logger.exception(
                "Plugin %s failed to generate preview",
                sanitize_log_field(plugin_id),
            )
            _push_update_now_fallback(
                plugin_id, plugin_config, device_config, display_manager, e
            )
            return json_error(
                _ERR_INTERNAL,
                status=400,
                code="plugin_error",
            )
        except Exception:
            # Unexpected exceptions must not leak exception text to the client
            # (JTN-318): could contain stack-traces, DB credentials, etc.
            logger.exception(
                "Unexpected error generating preview for plugin %s",
                sanitize_log_field(plugin_id),
            )
            _push_update_now_fallback_from_current_exception(
                plugin_id, plugin_config, device_config, display_manager
            )
            return json_error(_ERR_INTERNAL, status=500, code="internal_error")
        generate_ms = int((perf_counter() - _t_gen_start) * 1000)
        history_meta = {
            "refresh_type": "Manual Update",
            "plugin_id": plugin_id,
            "playlist": None,
            "plugin_instance": None,
        }
        _safe_display_image(
            display_manager,
            image,
            plugin_config.get("image_settings", []),
            history_meta,
        )
        try:
            ri = device_config.get_refresh_info()
            display_ms = getattr(ri, "display_ms", None)
            preprocess_ms = getattr(ri, "preprocess_ms", None)
        except Exception:
            display_ms = preprocess_ms = None
        request_ms = int((perf_counter() - _t_req_start) * 1000)
        metrics = {
            "request_ms": request_ms,
            "display_ms": display_ms,
            "generate_ms": generate_ms,
            "preprocess_ms": preprocess_ms,
            "steps": tracker.get_steps(),
        }
    return json_success(message=_MSG_DISPLAY_UPDATED, metrics=metrics)


def _push_update_now_fallback(
    plugin_id, plugin_config, device_config, display_manager, exc
):
    """Best-effort: render and push an error-card image so the display updates on failure."""
    try:
        w, h = device_config.get_resolution()
        fallback = render_error_image(
            width=w,
            height=h,
            plugin_id=plugin_id,
            instance_name=None,
            error_class=type(exc).__name__,
            error_message=str(exc),
        )
        _safe_display_image(
            display_manager,
            fallback,
            plugin_config.get("image_settings", []),
            {
                "refresh_type": "Manual Update",
                "plugin_id": plugin_id,
                "playlist": None,
                "plugin_instance": None,
                "error_class": type(exc).__name__,
            },
        )
    except Exception:
        logger.warning(
            "update_now: fallback display failed for %s",
            sanitize_log_field(plugin_id),
            exc_info=True,
        )


def _push_update_now_fallback_from_current_exception(
    plugin_id, plugin_config, device_config, display_manager
):
    """Variant of _push_update_now_fallback that uses the currently-raised exception.

    Centralised so callers don't need to capture the exception into a local
    variable (which would make it too tempting to embed the raw ``str(exc)``
    in the JSON error response).  The exception text is still rendered on the
    fallback image because that image is pushed to the e-paper screen, not
    returned via HTTP.
    """
    import sys

    exc = sys.exc_info()[1]
    if exc is None:
        return
    _push_update_now_fallback(
        plugin_id, plugin_config, device_config, display_manager, exc
    )


@plugin_bp.route("/api/job/<job_id>", methods=["GET"])
def job_status(job_id: str):
    """Poll the status of an asynchronous render job."""
    queue = get_job_queue()
    info = queue.get_status(job_id)
    return jsonify(info), 200


def _run_update_now(app, plugin_id, plugin_settings):
    """Execute plugin render in a background thread (job-queue worker).

    Needs the Flask *app* so we can push an application context — the worker
    thread has none by default.
    """
    with app.app_context():
        device_config = app.config[_CONFIG_KEY]
        refresh_task = app.config["REFRESH_TASK"]
        display_manager = app.config["DISPLAY_MANAGER"]

        if refresh_task.running:
            metrics = refresh_task.manual_update(
                ManualRefresh(plugin_id, plugin_settings)
            )
            return {
                "success": True,
                "message": _MSG_DISPLAY_UPDATED,
                "metrics": metrics,
            }

        logger.info("Refresh task not running, updating display directly")
        plugin_config = device_config.get_plugin(plugin_id)
        if not plugin_config:
            raise RuntimeError(f"Plugin '{plugin_id}' not found")

        plugin = get_plugin_instance(plugin_config)
        with track_progress() as tracker:
            _t_req_start = perf_counter()
            _t_gen_start = perf_counter()
            image = plugin.generate_image(plugin_settings, device_config)
            generate_ms = int((perf_counter() - _t_gen_start) * 1000)
            history_meta = {
                "refresh_type": "Manual Update",
                "plugin_id": plugin_id,
                "playlist": None,
                "plugin_instance": None,
            }
            _safe_display_image(
                display_manager,
                image,
                plugin_config.get("image_settings", []),
                history_meta,
            )
            try:
                ri = device_config.get_refresh_info()
                display_ms = getattr(ri, "display_ms", None)
                preprocess_ms = getattr(ri, "preprocess_ms", None)
            except Exception:
                display_ms = preprocess_ms = None
            request_ms = int((perf_counter() - _t_req_start) * 1000)
            return {
                "success": True,
                "message": _MSG_DISPLAY_UPDATED,
                "metrics": {
                    "request_ms": request_ms,
                    "display_ms": display_ms,
                    "generate_ms": generate_ms,
                    "preprocess_ms": preprocess_ms,
                    "steps": tracker.get_steps(),
                },
            }


@plugin_bp.route("/update_now", methods=["POST"])
def update_now():
    """Render a plugin image and push it to the display.

    When the client sends ``X-Async: true`` (or ``?async=1``), the render is
    enqueued on a background thread and the response is **202 Accepted** with
    ``{"job_id": "…"}``.  The caller then polls ``GET /api/job/<job_id>``
    until status is ``done`` or ``error``.

    Without the async flag the request behaves synchronously (legacy mode) so
    existing callers and tests are unaffected.
    """
    device_config = current_app.config[_CONFIG_KEY]
    refresh_task = current_app.config["REFRESH_TASK"]
    display_manager = current_app.config["DISPLAY_MANAGER"]

    plugin_id: str | None = None
    try:
        plugin_settings = parse_form(request.form)
        plugin_settings.update(handle_request_files(request.files))
        plugin_id = plugin_settings.pop(_PLUGIN_ID, None)
        if not plugin_id:
            return json_error(
                _ERR_PLUGIN_ID_REQUIRED,
                status=422,
                code="validation_error",
                details={"field": _PLUGIN_ID},
            )

        want_async = request.headers.get(
            "X-Async", ""
        ).lower() == "true" or request.args.get("async", "").lower() in ("1", "true")

        if want_async:
            queue = get_job_queue()
            app = current_app._get_current_object()  # real app, not proxy
            job_id = queue.enqueue(_run_update_now, app, plugin_id, plugin_settings)
            return jsonify({"job_id": job_id}), 202

        # --- Synchronous (legacy) path ---
        if refresh_task.running:
            metrics = refresh_task.manual_update(
                ManualRefresh(plugin_id, plugin_settings)
            )
            return json_success(message=_MSG_DISPLAY_UPDATED, metrics=metrics)
        logger.info("Refresh task not running, updating display directly")
        return _update_now_direct(
            plugin_id, plugin_settings, device_config, display_manager
        )
    except URLValidationError as e:
        # JTN-776: URL validation failures surfaced through the refresh-task
        # path (manual_update re-raises the plugin's exception) must become
        # HTTP 4xx, not 500, so the user sees the real reason. ``safe_message``
        # returns a whitelisted string from :mod:`utils.security_utils`, so no
        # exception-derived text reaches the response body (CodeQL
        # ``py/stack-trace-exposure``).
        safe_msg = e.safe_message()
        logger.info(
            "update_now: URL validation rejected plugin %s: %s",
            sanitize_log_field(plugin_id or "?"),
            sanitize_log_field(safe_msg),
        )
        return json_error(
            safe_msg,
            status=422,
            code="validation_error",
            details={"field": "url"},
        )
    except Exception as e:
        logger.exception("Error in update_now: %s", e)
        return json_error(_ERR_INTERNAL, status=500, code="internal_error")


@plugin_bp.route("/save_plugin_settings", methods=["POST"])
def save_plugin_settings():
    device_config = current_app.config[_CONFIG_KEY]
    playlist_manager = device_config.get_playlist_manager()
    htmx = _is_htmx_request()

    try:
        plugin_settings = parse_form(request.form)
        plugin_settings.update(handle_request_files(request.files))
        plugin_id = plugin_settings.pop(_PLUGIN_ID, None)
        if not plugin_id:
            if htmx:
                return _render_plugin_form_error(
                    _ERR_PLUGIN_ID_REQUIRED, status=422, field=_PLUGIN_ID
                )
            return json_error(
                _ERR_PLUGIN_ID_REQUIRED,
                status=422,
                code="validation_error",
                details={"field": _PLUGIN_ID},
            )
        return _save_plugin_settings_common(
            plugin_id=plugin_id,
            plugin_settings=plugin_settings,
            device_config=device_config,
            playlist_manager=playlist_manager,
        )
    except Exception as e:
        logger.exception("Error saving plugin settings: %s", e)
        if htmx:
            return _render_plugin_form_error(_ERR_INTERNAL, status=500)
        return json_error(_ERR_INTERNAL, status=500)


@plugin_bp.route("/plugin/<string:plugin_id>/save", methods=["POST"])
def save_plugin_settings_alias(plugin_id: str):
    """Backward-compatible route alias for plugin settings save."""
    device_config = current_app.config[_CONFIG_KEY]
    playlist_manager = device_config.get_playlist_manager()

    try:
        plugin_settings = parse_form(request.form)
        plugin_settings.update(handle_request_files(request.files))
        return _save_plugin_settings_common(
            plugin_id=plugin_id,
            plugin_settings=plugin_settings,
            device_config=device_config,
            playlist_manager=playlist_manager,
        )
    except Exception:
        logger.exception("Error saving plugin settings (alias)")
        if _is_htmx_request():
            return _render_plugin_form_error(_ERR_INTERNAL, status=500)
        return json_error(_ERR_INTERNAL, status=500)


def _is_htmx_request() -> bool:
    """Return True when the current request originated from HTMX (JTN-506)."""
    try:
        return request.headers.get("HX-Request", "").lower() == "true"
    except RuntimeError:
        # Outside an active request context
        return False


def _render_plugin_form_error(
    message: str, status: int = 400, field: str | None = None
):
    """Return an HTML error partial for the plugin settings form (JTN-506).

    HTMX swaps error content into ``#plugin-form-errors``; Flask clients that
    still speak JSON never see this branch because it's gated on the
    ``HX-Request`` header in the caller.
    """
    html = render_template(
        "partials/plugin_form_errors.html",
        error=message,
        field=field,
    )
    resp = make_response(html, status)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    return resp


def _render_plugin_form_success(message: str):
    """Return an HTMX success partial; fires ``pluginSettingsSaved`` toast event."""
    html = render_template(
        "partials/plugin_form_errors.html",
        error=None,
        message=message,
    )
    resp = make_response(html, 200)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    # HX-Trigger lets the existing toast JS fire without a duplicate modal path
    resp.headers["HX-Trigger"] = json.dumps(
        {"pluginSettingsSaved": {"message": message}}
    )
    return resp


def _save_plugin_settings_common(
    plugin_id, plugin_settings, device_config, playlist_manager
):
    htmx = _is_htmx_request()
    result = save_plugin_settings_workflow(
        plugin_id,
        plugin_settings,
        device_config,
        playlist_manager,
    )
    if not result.ok:
        error = result.error
        if error is None:
            logger.error(
                "_save_plugin_settings_common: workflow failed without error plugin_id=%s",
                sanitize_log_field(plugin_id),
            )
            if htmx:
                return _render_plugin_form_error(_ERR_INTERNAL, status=500)
            return json_error(_ERR_INTERNAL, status=500, code="internal_error")
        if htmx:
            return _render_plugin_form_error(
                error.message,
                status=error.status,
                field=error.field,
            )
        return json_error(error.message, **error.as_json_kwargs())

    success_message = result.message
    if htmx:
        return _render_plugin_form_success(success_message)
    return json_success(
        message=success_message,
        instance_name=result.instance_name,
    )


def _find_history_image(
    device_config, plugin_id: str, instance_name: str
) -> str | None:
    """Return path to a history PNG that matches plugin and instance, if any.

    Pre-filters directory listing to only .json filenames and sorts newest-first
    so the first match wins.
    """
    try:
        history_dir: str = str(device_config.history_image_dir)
        if not os.path.isdir(history_dir):
            return None
        json_files = sorted(
            (n for n in os.listdir(history_dir) if n.endswith(".json")),
            reverse=True,
        )
        for name in json_files:
            json_path = os.path.join(history_dir, name)
            try:
                with open(json_path, encoding="utf-8") as fh:
                    meta = json.load(fh)
                if (
                    meta.get(_PLUGIN_ID) == plugin_id
                    and meta.get("plugin_instance") == instance_name
                ):
                    png_path: str = os.path.join(
                        history_dir, name.replace(".json", ".png")
                    )
                    if os.path.exists(png_path):
                        return png_path
            except Exception:
                continue
    except Exception:
        return None
    return None


def _find_latest_plugin_refresh_time(device_config, plugin_id: str) -> str | None:
    """Return the most recent refresh time for any instance of this plugin.

    Filenames follow the display_YYYYMMDD_HHMMSS pattern, so sorting by
    filename descending mirrors refresh_time ordering.  We iterate
    newest-first and return the refresh_time from the first match.
    """
    try:
        history_dir = str(device_config.history_image_dir)
        if not os.path.isdir(history_dir):
            return None

        json_files = sorted(
            (n for n in os.listdir(history_dir) if n.endswith(".json")),
            reverse=True,
        )

        for name in json_files:
            json_path = os.path.join(history_dir, name)
            try:
                with open(json_path, encoding="utf-8") as fh:
                    meta = json.load(fh)
                if meta.get(_PLUGIN_ID) == plugin_id:
                    refresh_time = meta.get("refresh_time")
                    if refresh_time:
                        return refresh_time
            except Exception:
                continue

        return None
    except Exception:
        return None


@plugin_bp.route(
    "/instance_image/<string:plugin_id>/<string:instance_name>",
    endpoint="plugin_instance_image",
    methods=["GET"],
)
def instance_image(plugin_id: str, instance_name: str):
    device_config = current_app.config[_CONFIG_KEY]
    playlist_manager = device_config.get_playlist_manager()

    # Resolve expected image path
    try:
        path = device_config.get_plugin_image_path(plugin_id, instance_name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except Exception:
        return (_ERR_NOT_FOUND, 404)

    # Serve if already exists
    if os.path.exists(path):
        return _cacheable_send_file(path)

    # Try to generate and persist
    try:
        plugin_inst = playlist_manager.find_plugin(plugin_id, instance_name)
        if not plugin_inst:
            return (_ERR_NOT_FOUND, 404)
        plugin_config = device_config.get_plugin(plugin_id)
        if not plugin_config:
            return (_ERR_NOT_FOUND, 404)
        plugin = get_plugin_instance(plugin_config)
        image = plugin.generate_image(plugin_inst.settings, device_config)
        image.save(path)
        return _cacheable_send_file(path)
    except Exception:
        # Fallback to most recent matching history image
        hist = _find_history_image(device_config, plugin_id, instance_name)
        if hist and os.path.exists(hist):
            return _cacheable_send_file(hist)
        return (_ERR_NOT_FOUND, 404)
