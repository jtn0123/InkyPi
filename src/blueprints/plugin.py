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

logger = logging.getLogger(__name__)
plugin_bp = Blueprint("plugin", __name__)

PLUGINS_DIR = resolve_path("plugins")


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
                template_params["plugin_instance_last_refresh"] = (
                    plugin_instance.latest_refresh_time
                )
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

    # Prevent path traversal and ensure file exists
    if not path.startswith(base_dir + os.sep) or not os.path.exists(path):
        logger.info(
            "Instance image missing, attempting dev fallback | plugin_id=%s instance=%s path=%s",
            plugin_id,
            instance_name,
            path,
        )
        # Dev fallback: if instance image not yet created, try to generate from saved settings
        try:
            device_config = current_app.config["DEVICE_CONFIG"]
            playlist_manager = device_config.get_playlist_manager()
            plugin_config = device_config.get_plugin(plugin_id)
            if plugin_config:
                plugin = get_plugin_instance(plugin_config)
                # Try to find instance in any playlist
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
                if inst:
                    # Generate image and persist to plugin image dir
                    image = plugin.generate_image(inst.settings, device_config)
                    os.makedirs(base_dir, exist_ok=True)
                    image.save(path)
                    logger.info("Generated instance image | path=%s", path)
        except Exception:
            # Ignore failures; keep 404 behavior below if still missing
            logger.exception("Failed to generate instance image in dev fallback")
        if not os.path.exists(path):
            # Second fallback: search history sidecars for latest matching plugin/instance and serve that PNG
            try:
                device_config = current_app.config["DEVICE_CONFIG"]
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
                                # sidecar base name matches PNG filename
                                png_name = fname.replace(".json", ".png")
                                latest_match = _os.path.join(history_dir, png_name)
                    except Exception:
                        continue
                if latest_match and os.path.exists(latest_match):
                    logger.info(
                        "Serving instance image from history fallback | plugin_id=%s instance=%s history=%s",
                        plugin_id,
                        instance_name,
                        latest_match,
                    )
                    return send_file(
                        latest_match, mimetype="image/png", conditional=True
                    )
            except Exception:
                logger.exception("Failed during history fallback for instance image")
            return abort(404)

    return send_file(path, mimetype="image/png", conditional=True)


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
        refresh_task.manual_update(
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
    try:
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

    try:
        # Start timing (request overall)
        from time import perf_counter

        _t_req_start = perf_counter()
        plugin_settings = parse_form(request.form)
        plugin_settings.update(handle_request_files(request.files))
        plugin_id = plugin_settings.pop("plugin_id")
        instance_name = plugin_settings.get("instance_name")

        # Check if refresh task is running
        if refresh_task.running:
            refresh_task.manual_update(ManualRefresh(plugin_id, plugin_settings))
        else:
            # In development mode, directly update the display
            logger.info("Refresh task not running, updating display directly")
            plugin_config = device_config.get_plugin(plugin_id)
            if not plugin_config:
                return json_error(f"Plugin '{plugin_id}' not found", status=404)

            plugin = get_plugin_instance(plugin_config)
            _t_gen_start = perf_counter()
            image = plugin.generate_image(plugin_settings, device_config)
            generate_ms = int((perf_counter() - _t_gen_start) * 1000)
            # Pass history metadata even in direct dev path
            history_meta = {
                "refresh_type": "Manual Update",
                "plugin_id": plugin_id,
                "playlist": None,
                "plugin_instance": instance_name,
            }
            try:
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
