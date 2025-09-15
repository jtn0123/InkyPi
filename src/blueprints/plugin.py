import logging
import os

from flask import (
    Blueprint,
    abort,
    current_app,
    jsonify,
    render_template,
    request,
    send_file,
)

from plugins.plugin_registry import get_plugin_instance
from refresh_task import ManualRefresh, PlaylistRefresh
from utils.app_utils import handle_request_files, parse_form, resolve_path
from utils.http_utils import APIError, json_error, json_internal_error, json_success
from utils.progress import ProgressTracker, track_progress
from uuid import uuid4

try:
    from benchmarks.benchmark_storage import save_refresh_event, save_stage_event
except Exception:  # pragma: no cover
    def save_refresh_event(*args, **kwargs):  # type: ignore
        return None

    def save_stage_event(*args, **kwargs):  # type: ignore
        return None

logger = logging.getLogger(__name__)
plugin_bp = Blueprint("plugin", __name__)

PLUGINS_DIR = resolve_path("plugins")


def _generate_instance_image_from_saved_settings(
    device_config, plugin_id: str, instance_name: str, path: str
) -> bool:
    """Attempt to generate and persist an instance image using saved settings.

    Returns True on success, False otherwise. Any exception is caught and logged
    with contextual information.
    """

    try:
        plugin_config = device_config.get_plugin(plugin_id)
        if not plugin_config:
            logger.error(
                "Dev fallback plugin config not found | plugin_id=%s", plugin_id
            )
            return False

        plugin = get_plugin_instance(plugin_config)
        playlist_manager = device_config.get_playlist_manager()
        inst = None
        for name in playlist_manager.get_playlist_names():
            pl = playlist_manager.get_playlist(name)
            if pl:
                inst = pl.find_plugin(plugin_id, instance_name)
                if inst:
                    logger.info(
                        "Found instance in playlist | playlist=%s plugin_id=%s instance=%s",
                        name,
                        plugin_id,
                        instance_name,
                    )
                    break

        if not inst:
            logger.error(
                "Dev fallback instance not found | plugin_id=%s instance=%s",
                plugin_id,
                instance_name,
            )
            return False

        image = plugin.generate_image(inst.settings, device_config)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        image.save(path)
        logger.info(
            "Generated instance image | plugin_id=%s instance=%s path=%s",
            plugin_id,
            instance_name,
            path,
        )
        return True
    except Exception:
        logger.exception(
            "Dev fallback failed | plugin_id=%s instance=%s path=%s",
            plugin_id,
            instance_name,
            path,
        )
        return False


def _get_instance_image_from_history(device_config, plugin_id: str, instance_name: str):
    """Locate latest history PNG for a plugin instance based on sidecar metadata."""

    try:
        history_dir = device_config.history_image_dir
        latest_match = None
        latest_mtime: float = -1.0
        for fname in os.listdir(history_dir):
            if not fname.endswith(".json"):
                continue
            import json
            import os as _os

            p = _os.path.join(history_dir, fname)
            try:
                with open(p, encoding="utf-8") as fh:
                    meta = json.load(fh) or {}
                if (
                    meta.get("plugin_id") == plugin_id
                    and meta.get("plugin_instance") == instance_name
                ):
                    mtime = _os.path.getmtime(p)
                    if mtime > latest_mtime:
                        latest_mtime = mtime
                        png_name = fname.replace(".json", ".png")
                        latest_match = _os.path.join(history_dir, png_name)
            except Exception:
                logger.exception("Failed reading history sidecar | path=%s", p)

        if latest_match and os.path.exists(latest_match):
            logger.info(
                "Serving instance image from history fallback | plugin_id=%s instance=%s history=%s",
                plugin_id,
                instance_name,
                latest_match,
            )
            return latest_match
    except Exception:
        logger.exception(
            "History fallback failed | plugin_id=%s instance=%s",
            plugin_id,
            instance_name,
        )
    return None


def _get_latest_plugin_history_image(device_config, plugin_id: str):
    """Return tuple (png_path, saved_at_iso_str|None) for the latest history image for a plugin.

    Searches the history sidecar JSON files for entries matching the plugin_id
    irrespective of instance, and returns the PNG path and saved_at timestamp
    (converted to ISO string) of the newest one.
    """

    try:
        history_dir = device_config.history_image_dir
        latest_match = None
        latest_saved_at_iso: str | None = None
        latest_mtime: float = -1.0
        for fname in os.listdir(history_dir):
            if not fname.endswith(".json"):
                continue
            import json as _json
            import os as _os

            p = _os.path.join(history_dir, fname)
            try:
                with open(p, encoding="utf-8") as fh:
                    meta = _json.load(fh) or {}
                if meta.get("plugin_id") == plugin_id:
                    mtime = _os.path.getmtime(p)
                    if mtime > latest_mtime:
                        latest_mtime = mtime
                        png_name = fname.replace(".json", ".png")
                        latest_match = _os.path.join(history_dir, png_name)
                        saved_at = meta.get("saved_at")
                        if saved_at:
                            try:
                                from datetime import datetime as _dt

                                dt = _dt.strptime(saved_at, "%Y%m%d_%H%M%S")
                                latest_saved_at_iso = dt.isoformat()
                            except Exception:
                                latest_saved_at_iso = saved_at
            except Exception:
                logger.exception("Failed reading plugin history sidecar | path=%s", p)

        if latest_match and os.path.exists(latest_match):
            logger.info(
                "Resolved latest plugin history image | plugin_id=%s history=%s",
                plugin_id,
                latest_match,
            )
            return latest_match, latest_saved_at_iso
    except Exception:
        logger.exception(
            "Latest plugin history lookup failed | plugin_id=%s", plugin_id
        )
    return None, None


@plugin_bp.route("/plugin/<plugin_id>")
def plugin_page(plugin_id):
    device_config = current_app.config["DEVICE_CONFIG"]
    playlist_manager = device_config.get_playlist_manager()

    # Find the plugin by id
    plugin_config = device_config.get_plugin(plugin_id)
    if plugin_config:
        try:
            plugin = get_plugin_instance(plugin_config)
            template_params = plugin.generate_settings_template()

            # Check API key presence if required
            if "api_key" in template_params and template_params["api_key"].get("required"):
                expected_key = template_params["api_key"].get("expected_key")
                if expected_key:
                    api_key_value = device_config.load_env_key(expected_key)
                    template_params["api_key"]["present"] = bool(api_key_value)
                else:
                    template_params["api_key"]["present"] = False

            # retrieve plugin instance from the query parameters if updating existing plugin instance
            plugin_instance_name = request.args.get("instance")
            logger.info(
                "Render plugin page | plugin_id=%s instance=%s",
                plugin_id,
                plugin_instance_name,
            )
            if plugin_instance_name:
                plugin_instance = playlist_manager.find_plugin(
                    plugin_id, plugin_instance_name
                )
                if not plugin_instance:
                    return json_error(
                        f"Plugin instance: {plugin_instance_name} does not exist",
                        status=500,
                    )

                # add plugin instance settings to the template to prepopulate
                template_params["plugin_settings"] = plugin_instance.settings
                template_params["plugin_instance"] = plugin_instance_name
                # expose latest refresh time for this instance (for UI status)
                last_refresh_ts = plugin_instance.latest_refresh_time
                if not last_refresh_ts:
                    # Derive from history sidecars if available
                    try:
                        import json as _json
                        import os as _os

                        history_dir = device_config.history_image_dir
                        latest_mtime: float = -1.0
                        latest_saved_at: str | None = None
                        for fname in _os.listdir(history_dir):
                            if not fname.endswith(".json"):
                                continue
                            p = _os.path.join(history_dir, fname)
                            try:
                                with open(p, encoding="utf-8") as fh:
                                    meta = _json.load(fh) or {}
                                if (
                                    meta.get("plugin_id") == plugin_id
                                    and meta.get("plugin_instance")
                                    == plugin_instance_name
                                ):
                                    mtime = _os.path.getmtime(p)
                                    if mtime > latest_mtime:
                                        latest_mtime = mtime
                                        latest_saved_at = meta.get("saved_at")
                            except Exception:
                                logger.exception(
                                    "Failed reading history sidecar for last refresh | path=%s",
                                    p,
                                )
                        # saved_at is in '%Y%m%d_%H%M%S'; keep raw for JS to format? we can convert to ISO
                        if latest_saved_at:
                            try:
                                from datetime import datetime as _dt

                                dt = _dt.strptime(latest_saved_at, "%Y%m%d_%H%M%S")
                                last_refresh_ts = dt.isoformat()
                            except Exception:
                                last_refresh_ts = latest_saved_at
                    except Exception:
                        logger.exception("History fallback for last_refresh failed")
                template_params["plugin_instance_last_refresh"] = last_refresh_ts
                # find and expose the playlist containing this instance for UI actions
                try:
                    playlist_name = None
                    for name in playlist_manager.get_playlist_names():
                        pl = playlist_manager.get_playlist(name)
                        if pl and pl.find_plugin(plugin_id, plugin_instance_name):
                            playlist_name = name
                            break
                    logger.info(
                        "Resolved instance playlist | plugin_id=%s instance=%s playlist=%s",
                        plugin_id,
                        plugin_instance_name,
                        playlist_name,
                    )
                    template_params["plugin_instance_playlist"] = playlist_name
                except Exception:
                    logger.exception("Failed resolving instance playlist")
                    template_params["plugin_instance_playlist"] = None
            else:
                # Load saved settings for this plugin (non-recurring; not tied to a playlist)
                try:
                    saved = device_config.get_config("saved_settings", {}).get(
                        plugin_id
                    )
                    if saved:
                        template_params["plugin_settings"] = saved
                        template_params["plugin_instance"] = ""
                        template_params["plugin_instance_last_refresh"] = None
                        template_params["plugin_instance_playlist"] = None
                        logger.info(
                            "Loaded saved settings | plugin_id=%s",
                            plugin_id,
                        )
                except Exception:
                    # Best-effort; continue without saved settings
                    pass

                # Regardless of saved settings, try to surface latest plugin history for UI
                try:
                    _png_path, latest_ts = _get_latest_plugin_history_image(
                        device_config, plugin_id
                    )
                    template_params["plugin_latest_refresh"] = latest_ts
                except Exception:
                    template_params["plugin_latest_refresh"] = None

            template_params["playlists"] = playlist_manager.get_playlist_names()
        except Exception as e:
            logger.exception("EXCEPTION CAUGHT: " + str(e))
            return json_internal_error(
                "render plugin settings page",
                details={
                    "plugin_id": plugin_id,
                    "hint": "Verify plugin class and settings template load correctly.",
                },
            )
        return render_template(
            "plugin.html",
            plugin=plugin_config,
            resolution=device_config.get_resolution(),
            config=device_config.get_config(),
            **template_params,
        )
    else:
        return "Plugin not found", 404


@plugin_bp.route("/images/<plugin_id>/<path:filename>")
def image(plugin_id, filename):
    # Serve files from the specific plugin subdirectory
    plugin_dir = os.path.abspath(os.path.join(PLUGINS_DIR, plugin_id))
    full_path = os.path.abspath(os.path.join(plugin_dir, filename))
    # Prevent path traversal
    if not full_path.startswith(plugin_dir + os.sep):
        return abort(404)
    if not os.path.exists(full_path):
        return abort(404)
    return send_file(full_path)


@plugin_bp.route("/instance_image/<string:plugin_id>/<string:instance_name>")
def plugin_instance_image(plugin_id, instance_name):
    device_config = current_app.config["DEVICE_CONFIG"]
    from model import PluginInstance

    # Compute expected filename for this instance
    filename = PluginInstance(plugin_id, instance_name, {}, {}).get_image_path()

    base_dir = os.path.abspath(device_config.plugin_image_dir)
    path = os.path.abspath(os.path.join(base_dir, filename))

    # Prevent path traversal
    if not path.startswith(base_dir + os.sep):
        logger.error(
            "Invalid instance image path | plugin_id=%s instance=%s path=%s",
            plugin_id,
            instance_name,
            path,
        )
        return abort(404, description="Instance image not found")

    if not os.path.exists(path):
        logger.info(
            "Instance image missing, attempting fallbacks | plugin_id=%s instance=%s path=%s",
            plugin_id,
            instance_name,
            path,
        )
        # Try dev generation from saved settings
        success = _generate_instance_image_from_saved_settings(
            device_config, plugin_id, instance_name, path
        )
        if not success:
            # Try history sidecar fallback
            history_path = _get_instance_image_from_history(
                device_config, plugin_id, instance_name
            )
            if history_path:
                return send_file(history_path, mimetype="image/png", conditional=True)
            logger.error(
                "Instance image fallbacks failed | plugin_id=%s instance=%s path=%s",
                plugin_id,
                instance_name,
                path,
            )
            return abort(404, description="Instance image not found")

    return send_file(path, mimetype="image/png", conditional=True)


@plugin_bp.route("/plugin_latest_image/<string:plugin_id>")
def plugin_latest_image(plugin_id):
    """Serve the most recent processed image for a given plugin from history.

    Falls back to 404 when none are available.
    """
    device_config = current_app.config["DEVICE_CONFIG"]
    png_path, _ts = _get_latest_plugin_history_image(device_config, plugin_id)
    if png_path and os.path.exists(png_path):
        return send_file(png_path, mimetype="image/png", conditional=True)
    return abort(404)


@plugin_bp.route("/delete_plugin_instance", methods=["POST"])
def delete_plugin_instance():
    device_config = current_app.config["DEVICE_CONFIG"]
    playlist_manager = device_config.get_playlist_manager()

    data = request.json
    if not data:
        return json_error("Invalid JSON data", status=400)

    playlist_name = data.get("playlist_name")
    plugin_id = data.get("plugin_id")
    plugin_instance = data.get("plugin_instance")

    try:
        playlist = playlist_manager.get_playlist(playlist_name)
        if not playlist:
            return json_error("Playlist not found", status=400)

        result = playlist.delete_plugin(plugin_id, plugin_instance)
        if not result:
            return json_error("Plugin instance not found", status=400)

        # save changes to device config file
        device_config.write_config()

    except Exception as e:
        logger.exception("EXCEPTION CAUGHT: " + str(e))
        return json_internal_error(
            "delete plugin instance",
            details={"hint": "Check playlist exists and instance name is correct."},
        )

    return json_success("Deleted plugin instance.")


@plugin_bp.route("/update_plugin_instance/<string:instance_name>", methods=["PUT"])
def update_plugin_instance(instance_name):
    device_config = current_app.config["DEVICE_CONFIG"]
    playlist_manager = device_config.get_playlist_manager()

    try:
        form_data = parse_form(request.form)

        if not instance_name:
            raise APIError("Instance name is required", status=400)
        plugin_settings = form_data
        plugin_settings.update(handle_request_files(request.files, request.form))

        plugin_id = plugin_settings.pop("plugin_id")
        plugin_instance = playlist_manager.find_plugin(plugin_id, instance_name)
        if not plugin_instance:
            return json_error(
                f"Plugin instance: {instance_name} does not exist", status=500
            )

        plugin_instance.settings = plugin_settings
        device_config.write_config()
    except APIError as e:
        return json_error(e.message, status=e.status, code=e.code, details=e.details)
    except Exception:
        logger.exception("Error updating plugin instance")
        return json_internal_error(
            "update plugin instance",
            details={
                "hint": "Ensure instance exists; check config file write permissions."
            },
        )
    return jsonify(
        {"success": True, "message": f"Updated plugin instance {instance_name}."}
    )


@plugin_bp.route("/display_plugin_instance", methods=["POST"])
def display_plugin_instance():
    device_config = current_app.config["DEVICE_CONFIG"]
    refresh_task = current_app.config["REFRESH_TASK"]
    playlist_manager = device_config.get_playlist_manager()

    data = request.json
    if not data:
        return json_error("Invalid JSON data", status=400)

    playlist_name = data.get("playlist_name")
    plugin_id = data.get("plugin_id")
    plugin_instance_name = data.get("plugin_instance")

    try:
        playlist = playlist_manager.get_playlist(playlist_name)
        if not playlist:
            return json_error(f"Playlist {playlist_name} not found", status=400)

        plugin_instance = playlist.find_plugin(plugin_id, plugin_instance_name)
        if not plugin_instance:
            return json_error(
                f"Plugin instance '{plugin_instance_name}' not found", status=400
            )

        logger.info(
            "Display plugin instance requested | playlist=%s plugin_id=%s instance=%s",
            playlist_name,
            plugin_id,
            plugin_instance_name,
        )
        metrics = refresh_task.manual_update(
            PlaylistRefresh(playlist, plugin_instance, force=True)
        )
    except Exception:
        logger.exception("Error displaying plugin instance")
        return json_internal_error(
            "display plugin instance",
            details={"hint": "Ensure playlist and instance exist and are valid."},
        )
    # Include latest metrics from refresh info for richer UI feedback
    request_ms = display_ms = generate_ms = preprocess_ms = None
    steps = None
    try:
        if metrics:
            request_ms = metrics.get("request_ms")
            display_ms = metrics.get("display_ms")
            generate_ms = metrics.get("generate_ms")
            preprocess_ms = metrics.get("preprocess_ms")
            steps = metrics.get("steps")
        else:
            ri = device_config.get_refresh_info()
            request_ms = getattr(ri, "request_ms", None)
            display_ms = getattr(ri, "display_ms", None)
            generate_ms = getattr(ri, "generate_ms", None)
            preprocess_ms = getattr(ri, "preprocess_ms", None)
    except Exception:
        pass

    logger.info(
        "Display plugin instance metrics | request_ms=%s generate_ms=%s preprocess_ms=%s display_ms=%s",
        request_ms,
        generate_ms,
        preprocess_ms,
        display_ms,
    )

    return json_success(
        "Display updated",
        metrics={
            "request_ms": request_ms,
            "generate_ms": generate_ms,
            "preprocess_ms": preprocess_ms,
            "display_ms": display_ms,
            "steps": steps,
        },
    )


@plugin_bp.route("/update_now", methods=["POST"])
def update_now():
    device_config = current_app.config["DEVICE_CONFIG"]
    refresh_task = current_app.config["REFRESH_TASK"]
    display_manager = current_app.config["DISPLAY_MANAGER"]

    # Initialize timing variables
    request_ms: int | None = None
    display_ms: int | None = None
    generate_ms: int | None = None
    preprocess_ms: int | None = None
    steps = None

    try:
        # Start timing (request overall)
        from time import perf_counter

        _t_req_start = perf_counter()
        plugin_settings = parse_form(request.form)
        plugin_settings.update(handle_request_files(request.files))
        plugin_id = plugin_settings.pop("plugin_id")
        instance_name = plugin_settings.get("instance_name")

        # Check if refresh task is running
        benchmark_id = str(uuid4())
        if refresh_task.running:
            metrics = refresh_task.manual_update(
                ManualRefresh(plugin_id, plugin_settings)
            )
        else:
            # In development mode, directly update the display
            logger.info("Refresh task not running, updating display directly")
            plugin_config = device_config.get_plugin(plugin_id)
            if not plugin_config:
                return json_error(f"Plugin '{plugin_id}' not found", status=404)

            plugin = get_plugin_instance(plugin_config)
            tracker: ProgressTracker
            with track_progress() as tracker:
                _t_gen_start = perf_counter()
                image = plugin.generate_image(plugin_settings, device_config)
                try:
                    save_stage_event(device_config, benchmark_id, "generate_image", int((perf_counter() - _t_gen_start) * 1000))
                except Exception:
                    pass
            generate_ms = int((perf_counter() - _t_gen_start) * 1000)
            steps = tracker.get_steps()
            metrics = {
                "generate_ms": generate_ms,
                "display_ms": None,
                "preprocess_ms": None,
                "steps": steps,
            }
            # Pass history metadata even in direct dev path
            history_meta = {
                "refresh_type": "Manual Update",
                "plugin_id": plugin_id,
                "playlist": None,
                "plugin_instance": instance_name,
            }
            try:
                # Prepare minimal refresh_info so display manager can record preprocess/display
                from model import RefreshInfo
                from utils.image_utils import compute_image_hash
                from utils.time_utils import now_device_tz

                device_config.refresh_info = RefreshInfo(
                    refresh_type="Manual Update",
                    plugin_id=plugin_id,
                    refresh_time=now_device_tz(device_config).isoformat(),
                    image_hash=compute_image_hash(image),
                    request_ms=None,
                    display_ms=None,
                    generate_ms=generate_ms,
                    preprocess_ms=None,
                    used_cached=False,
                    benchmark_id=benchmark_id,
                    plugin_meta=None,
                )
                display_manager.display_image(
                    image,
                    image_settings=plugin_config.get("image_settings", []),
                    history_meta=history_meta,
                )
            except TypeError:
                # Back-compat for mocks/tests without history_meta param
                display_manager.display_image(
                    image,
                    image_settings=plugin_config.get("image_settings", []),
                )
            try:
                # Persist a refresh_event row for the dev path
                ri = device_config.get_refresh_info()
                cpu_percent = memory_percent = None
                try:
                    import psutil  # type: ignore

                    cpu_percent = psutil.cpu_percent(interval=None)
                    memory_percent = psutil.virtual_memory().percent
                except Exception:
                    pass
                save_refresh_event(
                    device_config,
                    {
                        "refresh_id": benchmark_id,
                        "ts": None,
                        "plugin_id": plugin_id,
                        "instance": instance_name,
                        "playlist": None,
                        "used_cached": False,
                        "request_ms": None,  # finalized below
                        "generate_ms": generate_ms,
                        "preprocess_ms": getattr(ri, "preprocess_ms", None),
                        "display_ms": getattr(ri, "display_ms", None),
                        "cpu_percent": cpu_percent,
                        "memory_percent": memory_percent,
                        "notes": "dev_update_now",
                    },
                )
            except Exception:
                pass
            # In dev path (no background task), persist minimal refresh_info with plugin_meta
            try:
                from model import RefreshInfo
                from utils.image_utils import compute_image_hash
                from utils.time_utils import now_device_tz

                meta = None
                if hasattr(plugin, "get_latest_metadata"):
                    meta = plugin.get_latest_metadata()
                device_config.refresh_info = RefreshInfo(
                    refresh_type="Manual Update",
                    plugin_id=plugin_id,
                    refresh_time=now_device_tz(device_config).isoformat(),
                    image_hash=compute_image_hash(image),
                    request_ms=None,
                    display_ms=None,
                    generate_ms=generate_ms,
                    preprocess_ms=None,
                    used_cached=False,
                    plugin_meta=meta,
                )
                device_config.write_config()
            except Exception:
                # Best-effort; do not fail the update path
                pass

    except Exception as e:
        logger.exception(f"Error in update_now: {str(e)}")
        return json_error(
            f"An error occurred: {str(e)}",
            status=500,
            details={"context": "update_now"},
        )

    # Build metrics payload from device_config.refresh_info (populated by task/display)
    try:
        if metrics:
            request_ms = metrics.get("request_ms", request_ms)
            display_ms = metrics.get("display_ms", display_ms)
            generate_ms = metrics.get("generate_ms", generate_ms)
            preprocess_ms = metrics.get("preprocess_ms", preprocess_ms)
            steps = metrics.get("steps", steps)
        else:
            ri = device_config.get_refresh_info()
            if request_ms is None:
                request_ms = getattr(ri, "request_ms", None)
            if display_ms is None:
                display_ms = getattr(ri, "display_ms", None)
            if generate_ms is None:
                generate_ms = getattr(ri, "generate_ms", None)
            if preprocess_ms is None:
                preprocess_ms = getattr(ri, "preprocess_ms", None)
    except Exception:
        pass

    # If timing wasn't captured by task path (e.g., direct dev path), compute minimal request_ms
    try:
        if request_ms is None:
            from time import perf_counter

            request_ms = int((perf_counter() - _t_req_start) * 1000)
    except Exception:
        pass

    return json_success(
        "Display updated",
        metrics={
            "request_ms": request_ms,
            "generate_ms": generate_ms,
            "preprocess_ms": preprocess_ms,
            "display_ms": display_ms,
            "steps": steps,
        },
    )


@plugin_bp.route("/ab_compare", methods=["POST"])
def ab_compare():
    device_config = current_app.config["DEVICE_CONFIG"]
    display_manager = current_app.config["DISPLAY_MANAGER"]

    try:
        form = parse_form(request.form)
        form.update(handle_request_files(request.files))
        plugin_id = form.get("plugin_id")
        extra_css = form.get("extra_css", "")
        if not plugin_id:
            return json_error("plugin_id required", status=400)

        plugin_config = device_config.get_plugin(plugin_id)
        if not plugin_config:
            return json_error(f"Plugin '{plugin_id}' not found", status=404)
        plugin = get_plugin_instance(plugin_config)

        # Baseline (A)
        image_a = plugin.generate_image(form, device_config)
        try:
            display_manager.save_image_only(image_a, filename="current_image.png")
        except Exception:
            target = resolve_path("static/images/current_image.png")
            image_a.save(target)

        # Variant (B)
        form_with_css = dict(form)
        form_with_css["extra_css"] = extra_css
        image_b = plugin.generate_image(form_with_css, device_config)
        try:
            display_manager.save_image_only(
                image_b, filename="current_image_variant.png"
            )
        except Exception:
            target_b = resolve_path("static/images/current_image_variant.png")
            image_b.save(target_b)

        from flask import url_for

        return jsonify(
            {
                "success": True,
                "baseline_path": url_for("static", filename="images/current_image.png"),
                "variant_path": url_for(
                    "static", filename="images/current_image_variant.png"
                ),
            }
        )
    except Exception:
        logger.exception("Error in ab_compare")
        return json_internal_error("ab compare")


@plugin_bp.route("/save_plugin_settings", methods=["POST"])
def save_plugin_settings():
    device_config = current_app.config["DEVICE_CONFIG"]

    try:
        plugin_settings = parse_form(request.form)
        plugin_settings.update(handle_request_files(request.files))
        plugin_id = plugin_settings.pop("plugin_id")

        # Persist settings under top-level saved_settings
        try:
            saved_all = device_config.get_config("saved_settings") or {}
        except Exception:
            saved_all = {}
        saved_all[plugin_id] = plugin_settings
        device_config.update_value("saved_settings", saved_all, write=True)

        return json_success(
            "Settings saved. Use 'Add to Playlist' to schedule recurrence."
        )

    except Exception as e:
        logger.exception(f"Error saving plugin settings: {str(e)}")
        return json_internal_error(
            "save plugin settings",
            details={
                "hint": "Check config file permissions.",
            },
        )


@plugin_bp.route("/weather/icon_preview", methods=["POST"])
def weather_icon_preview():
    from io import BytesIO

    from PIL import Image

    try:
        device_config = current_app.config["DEVICE_CONFIG"]
        form = parse_form(request.form)
        form.update(handle_request_files(request.files))
        plugin_id = form.get("plugin_id")
        if plugin_id != "weather":
            return json_error("plugin_id must be 'weather'", status=400)

        # Build four variant settings from form without changing saved settings
        base_settings = dict(form)
        packs = [
            ("current", "current"),
            ("A", "current"),
            ("B", "current"),
            ("C", form.get("moonIconPack") or "current"),
        ]

        from plugins.plugin_registry import get_plugin_instance

        plugin_config = device_config.get_plugin("weather")
        if not plugin_config:
            return json_error("Weather plugin not found", status=404)
        plugin = get_plugin_instance(plugin_config)

        # Render images using the same data fetch in a single request
        # (Weather plugin internally will fetch; these all happen back-to-back)
        imgs = []
        for w_pack, m_pack in packs:
            s = dict(base_settings)
            s["weatherIconPack"] = w_pack
            s["moonIconPack"] = m_pack
            try:
                img = plugin.generate_image(s, device_config)
            except Exception:
                # Fallback: create blank image
                from PIL import Image as _Image

                img = _Image.new("RGB", (800, 480), "white")
            imgs.append((img, f"{w_pack}"))

        # Composite horizontally
        h = max(im.height for im, _ in imgs)
        w = sum(im.width for im, _ in imgs)
        composite = Image.new("RGB", (w, h), "white")
        x = 0
        for im, _lbl in imgs:
            composite.paste(im, (x, 0))
            x += im.width

        fp = BytesIO()
        composite.save(fp, format="PNG")
        fp.seek(0)
        return current_app.response_class(fp.read(), mimetype="image/png")
    except Exception:
        logger.exception("Error in weather_icon_preview")
        return json_internal_error("weather icon preview")
