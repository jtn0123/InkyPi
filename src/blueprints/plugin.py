import json
import logging
import os
from time import perf_counter

from flask import (
    Blueprint,
    abort,
    current_app,
    jsonify,
    render_template,
    request,
    send_file,
    send_from_directory,
)

from plugins.plugin_registry import get_plugin_instance
from refresh_task import ManualRefresh, PlaylistRefresh
from utils.app_utils import handle_request_files, parse_form, resolve_path
from utils.http_utils import APIError, json_error
from utils.progress import track_progress

logger = logging.getLogger(__name__)
plugin_bp = Blueprint("plugin", __name__)

PLUGINS_DIR = resolve_path("plugins")


def _sanitize_log(value: str) -> str:
    """Strip control characters from user input before logging to prevent log injection."""
    return value.replace("\n", "").replace("\r", "").replace("\x00", "")[:200]


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
    return resp


@plugin_bp.route("/plugin/<plugin_id>")
def plugin_page(plugin_id: str):
    device_config = current_app.config["DEVICE_CONFIG"]
    playlist_manager = device_config.get_playlist_manager()

    plugin_config = device_config.get_plugin(plugin_id)
    if not plugin_config:
        return ("Plugin not found", 404)

    try:
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
                return json_error(
                    f"Plugin instance: {plugin_instance_name} does not exist", status=404
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

    except Exception as e:  # pragma: no cover - safety net
        logger.exception("EXCEPTION CAUGHT: %s", e)
        return json_error("An internal error occurred", status=500)

    return render_template(
        "plugin.html",
        plugin=plugin_config,
        resolution=device_config.get_resolution(),
        config=device_config.get_config(),
        **template_params,
    )


@plugin_bp.route("/images/<plugin_id>/<path:filename>")
def image(plugin_id: str, filename: str):
    # send_from_directory handles path traversal protection internally
    plugin_dir = os.path.abspath(os.path.join(PLUGINS_DIR, plugin_id))
    resp = send_from_directory(plugin_dir, filename)
    try:
        ttl = int(os.getenv("INKYPI_STATIC_PLUGIN_ASSET_TTL_S", "300") or "300")
    except Exception:
        ttl = 300
    resp.headers["Cache-Control"] = f"public, max-age={max(0, ttl)}"
    return resp


@plugin_bp.route(
    "/plugin_latest_image/<string:plugin_id>", endpoint="plugin_latest_image"
)
def latest_plugin_image(plugin_id: str):
    """Serve the most recent history image for a given plugin_id.

    Searches the history directory for the latest PNG matching the plugin_id,
    regardless of instance name. Used by the plugin page to show "Latest from this plugin".
    """
    device_config = current_app.config["DEVICE_CONFIG"]
    try:
        history_dir = str(device_config.history_image_dir)
        if not os.path.isdir(history_dir):
            return ("Not Found", 404)

        # Find all history images for this plugin, sorted by timestamp (newest first)
        matching_images = []
        for name in os.listdir(history_dir):
            if not name.endswith(".json"):
                continue
            json_path = os.path.join(history_dir, name)
            try:
                with open(json_path, encoding="utf-8") as fh:
                    meta = json.load(fh)
                if meta.get("plugin_id") == plugin_id:
                    png_path = os.path.join(history_dir, name.replace(".json", ".png"))
                    if os.path.exists(png_path):
                        # Extract timestamp from filename (format: display_YYYYMMDD_HHMMSS)
                        matching_images.append((name, png_path))
            except Exception:
                continue

        if not matching_images:
            return ("Not Found", 404)

        # Sort by filename (which includes timestamp) to get most recent
        matching_images.sort(reverse=True)
        latest_image_path = matching_images[0][1]
        return _cacheable_send_file(latest_image_path)

    except Exception:
        return ("Not Found", 404)


@plugin_bp.route("/delete_plugin_instance", methods=["POST", "DELETE"])
def delete_plugin_instance():
    device_config = current_app.config["DEVICE_CONFIG"]
    playlist_manager = device_config.get_playlist_manager()

    if not request.is_json:
        return json_error("Unsupported media type", status=415)
    data = request.json or {}

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

        device_config.write_config()

        # Clean up cached plugin instance image
        try:
            image_path = device_config.get_plugin_image_path(plugin_id, plugin_instance)
            if image_path and os.path.isfile(image_path):
                os.remove(image_path)
                logger.info("Removed cached image: %s", image_path)
        except Exception:
            logger.warning(
                "Could not clean up image for %s/%s",
                _sanitize_log(plugin_id), _sanitize_log(str(plugin_instance)),
                exc_info=True,
            )

        # Run plugin-specific cleanup (e.g., image_upload deletes uploaded files)
        try:
            plugin_obj = get_plugin_instance(plugin_id)
            if plugin_obj and hasattr(plugin_obj, "cleanup"):
                plugin_obj.cleanup({})
        except Exception:
            logger.warning("Plugin cleanup failed for %s", _sanitize_log(plugin_id), exc_info=True)
    except Exception as e:
        logger.exception("EXCEPTION CAUGHT: %s", e)
        return json_error("An internal error occurred", status=500)

    return jsonify({"success": True, "message": "Deleted plugin instance."})


@plugin_bp.route("/update_plugin_instance/<string:instance_name>", methods=["PUT"])
def update_plugin_instance(instance_name: str):
    device_config = current_app.config["DEVICE_CONFIG"]
    playlist_manager = device_config.get_playlist_manager()

    try:
        form_data = parse_form(request.form)
        if not instance_name:
            raise APIError(
                "Instance name is required",
                status=422,
                code="validation_error",
                details={"field": "instance_name"},
            )
        plugin_settings = form_data
        plugin_settings.update(handle_request_files(request.files, request.form))

        plugin_id = plugin_settings.pop("plugin_id", None)
        if not plugin_id:
            raise APIError(
                "plugin_id is required",
                status=422,
                code="validation_error",
                details={"field": "plugin_id"},
            )
        plugin_instance = playlist_manager.find_plugin(plugin_id, instance_name)
        if not plugin_instance:
            return json_error(
                f"Plugin instance: {instance_name} does not exist", status=404
            )

        plugin_instance.settings = plugin_settings
        device_config.write_config()
    except APIError as e:
        return json_error(e.message, status=e.status, code=e.code, details=e.details)
    except Exception:
        return json_error("An internal error occurred", status=500)

    return jsonify(
        {
            "success": True,
            "message": f"Updated plugin instance {instance_name}.",
        }
    )


@plugin_bp.route("/display_plugin_instance", methods=["POST"])
def display_plugin_instance():
    device_config = current_app.config["DEVICE_CONFIG"]
    refresh_task = current_app.config["REFRESH_TASK"]
    playlist_manager = device_config.get_playlist_manager()

    if not request.is_json:
        return json_error("Unsupported media type", status=415)
    data = request.json or {}

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

        refresh_task.manual_update(
            PlaylistRefresh(playlist, plugin_instance, force=True)
        )
    except Exception:
        return json_error("An internal error occurred", status=500)

    return jsonify({"success": True, "message": "Display updated"}), 200


@plugin_bp.route("/update_now", methods=["POST"])
def update_now():
    device_config = current_app.config["DEVICE_CONFIG"]
    refresh_task = current_app.config["REFRESH_TASK"]
    display_manager = current_app.config["DISPLAY_MANAGER"]

    try:
        plugin_settings = parse_form(request.form)
        plugin_settings.update(handle_request_files(request.files))
        plugin_id = plugin_settings.pop("plugin_id", None)
        if not plugin_id:
            return json_error(
                "plugin_id is required",
                status=422,
                code="validation_error",
                details={"field": "plugin_id"},
            )

        if refresh_task.running:
            metrics = refresh_task.manual_update(
                ManualRefresh(plugin_id, plugin_settings)
            )
            return (
                jsonify(
                    {"success": True, "message": "Display updated", "metrics": metrics}
                ),
                200,
            )
        else:
            logger.info("Refresh task not running, updating display directly")
            plugin_config = device_config.get_plugin(plugin_id)
            if not plugin_config:
                return json_error(f"Plugin '{plugin_id}' not found", status=404)

            plugin = get_plugin_instance(plugin_config)
            with track_progress() as tracker:
                _t_req_start = perf_counter()
                _t_gen_start = perf_counter()
                try:
                    image = plugin.generate_image(plugin_settings, device_config)
                except RuntimeError as e:
                    logger.warning("Plugin error in update_now: %s", e)
                    return json_error(str(e), status=400, code="plugin_error")
                generate_ms = int((perf_counter() - _t_gen_start) * 1000)
                display_manager.display_image(
                    image, image_settings=plugin_config.get("image_settings", [])
                )
                # Collect metrics from refresh_info if populated during display
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
            return (
                jsonify(
                    {"success": True, "message": "Display updated", "metrics": metrics}
                ),
                200,
            )
    except Exception as e:
        logger.exception("Error in update_now: %s", e)
        return json_error(
            "An internal error occurred", status=500, code="internal_error"
        )


@plugin_bp.route("/save_plugin_settings", methods=["POST"])
def save_plugin_settings():
    device_config = current_app.config["DEVICE_CONFIG"]
    playlist_manager = device_config.get_playlist_manager()

    try:
        plugin_settings = parse_form(request.form)
        plugin_settings.update(handle_request_files(request.files))
        plugin_id = plugin_settings.pop("plugin_id", None)
        if not plugin_id:
            return json_error(
                "plugin_id is required",
                status=422,
                code="validation_error",
                details={"field": "plugin_id"},
            )
        return _save_plugin_settings_common(
            plugin_id=plugin_id,
            plugin_settings=plugin_settings,
            device_config=device_config,
            playlist_manager=playlist_manager,
        )
    except Exception as e:
        logger.exception("Error saving plugin settings: %s", e)
        return json_error("An internal error occurred", status=500)


@plugin_bp.route("/plugin/<string:plugin_id>/save", methods=["POST"])
def save_plugin_settings_alias(plugin_id: str):
    """Backward-compatible route alias for plugin settings save."""
    device_config = current_app.config["DEVICE_CONFIG"]
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
        return json_error("An internal error occurred", status=500)


def _save_plugin_settings_common(
    plugin_id, plugin_settings, device_config, playlist_manager
):
    default_playlist_name = "Default"
    playlist = playlist_manager.get_playlist(default_playlist_name)
    if not playlist:
        playlist_manager.add_playlist(default_playlist_name)
        playlist = playlist_manager.get_playlist(default_playlist_name)

    instance_name = f"{plugin_id}_saved_settings"
    existing_instance = playlist.find_plugin(plugin_id, instance_name)
    if existing_instance:
        existing_instance.settings = plugin_settings
    else:
        playlist.add_plugin(
            {
                "plugin_id": plugin_id,
                "refresh": {"interval": 3600},
                "plugin_settings": plugin_settings,
                "name": instance_name,
            }
        )

    # Preserve legacy failure surface for callers/tests that patch config mutation hooks.
    device_config.update_value("playlist_config", playlist_manager.to_dict())
    device_config.write_config()
    return (
        jsonify(
            {
                "success": True,
                "message": "Settings saved. Add to Playlist to schedule this instance.",
                "instance_name": instance_name,
            }
        ),
        200,
    )


def _find_history_image(
    device_config, plugin_id: str, instance_name: str
) -> str | None:
    """Return path to a history PNG that matches plugin and instance, if any."""
    try:
        history_dir: str = str(device_config.history_image_dir)
        if not os.path.isdir(history_dir):
            return None
        for name in sorted(os.listdir(history_dir)):
            if not name.endswith(".json"):
                continue
            json_path = os.path.join(history_dir, name)
            try:
                with open(json_path, encoding="utf-8") as fh:
                    meta = json.load(fh)
                if (
                    meta.get("plugin_id") == plugin_id
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
    """Return the most recent refresh time for any instance of this plugin."""
    try:
        history_dir = str(device_config.history_image_dir)
        if not os.path.isdir(history_dir):
            return None

        latest_time = None
        for name in os.listdir(history_dir):
            if not name.endswith(".json"):
                continue
            json_path = os.path.join(history_dir, name)
            try:
                with open(json_path, encoding="utf-8") as fh:
                    meta = json.load(fh)
                if meta.get("plugin_id") == plugin_id:
                    refresh_time = meta.get("refresh_time")
                    if refresh_time:
                        if latest_time is None or refresh_time > latest_time:
                            latest_time = refresh_time
            except Exception:
                continue

        return latest_time
    except Exception:
        return None


@plugin_bp.route(
    "/instance_image/<string:plugin_id>/<string:instance_name>",
    endpoint="plugin_instance_image",
)
def instance_image(plugin_id: str, instance_name: str):
    device_config = current_app.config["DEVICE_CONFIG"]
    playlist_manager = device_config.get_playlist_manager()

    # Resolve expected image path
    try:
        path = device_config.get_plugin_image_path(plugin_id, instance_name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except Exception:
        return ("Not Found", 404)

    # Serve if already exists
    if os.path.exists(path):
        return _cacheable_send_file(path)

    # Try to generate and persist
    try:
        plugin_inst = playlist_manager.find_plugin(plugin_id, instance_name)
        if not plugin_inst:
            return ("Not Found", 404)
        plugin_config = device_config.get_plugin(plugin_id)
        if not plugin_config:
            return ("Not Found", 404)
        plugin = get_plugin_instance(plugin_config)
        image = plugin.generate_image(plugin_inst.settings, device_config)
        image.save(path)
        return _cacheable_send_file(path)
    except Exception:
        # Fallback to most recent matching history image
        hist = _find_history_image(device_config, plugin_id, instance_name)
        if hist and os.path.exists(hist):
            return _cacheable_send_file(hist)
        return ("Not Found", 404)
