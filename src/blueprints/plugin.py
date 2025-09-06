from flask import Blueprint, request, jsonify, current_app, render_template, send_from_directory, send_file, abort
from plugins.plugin_registry import get_plugin_instance
from utils.app_utils import resolve_path, handle_request_files, parse_form
from refresh_task import ManualRefresh, PlaylistRefresh
import json
import os
import logging

logger = logging.getLogger(__name__)
plugin_bp = Blueprint("plugin", __name__)

PLUGINS_DIR = resolve_path("plugins")

@plugin_bp.route('/plugin/<plugin_id>')
def plugin_page(plugin_id):
    device_config = current_app.config['DEVICE_CONFIG']
    playlist_manager = device_config.get_playlist_manager()

    # Find the plugin by id
    plugin_config = device_config.get_plugin(plugin_id)
    if plugin_config:
        try:
            plugin = get_plugin_instance(plugin_config)
            template_params = plugin.generate_settings_template()

            # retrieve plugin instance from the query parameters if updating existing plugin instance
            plugin_instance_name = request.args.get('instance')
            if plugin_instance_name:
                plugin_instance = playlist_manager.find_plugin(plugin_id, plugin_instance_name)
                if not plugin_instance:
                    return jsonify({"error": f"Plugin instance: {plugin_instance_name} does not exist"}), 500

                # add plugin instance settings to the template to prepopulate
                template_params["plugin_settings"] = plugin_instance.settings
                template_params["plugin_instance"] = plugin_instance_name
            else:
                # Try to find a saved settings instance for this plugin
                default_playlist = playlist_manager.get_playlist("Default")
                if default_playlist:
                    saved_instance_name = f"{plugin_id}_saved_settings"
                    saved_instance = default_playlist.find_plugin(plugin_id, saved_instance_name)
                    if saved_instance:
                        # Load the saved settings
                        template_params["plugin_settings"] = saved_instance.settings
                        template_params["plugin_instance"] = saved_instance_name

            template_params["playlists"] = playlist_manager.get_playlist_names()
        except Exception as e:
            logger.exception("EXCEPTION CAUGHT: " + str(e))
            return jsonify({"error": f"An error occurred: {str(e)}"}), 500
        return render_template(
            'plugin.html',
            plugin=plugin_config,
            resolution=device_config.get_resolution(),
            config=device_config.get_config(),
            **template_params
        )
    else:
        return "Plugin not found", 404

@plugin_bp.route('/images/<plugin_id>/<path:filename>')
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

@plugin_bp.route('/delete_plugin_instance', methods=['POST'])
def delete_plugin_instance():
    device_config = current_app.config['DEVICE_CONFIG']
    playlist_manager = device_config.get_playlist_manager()

    data = request.json
    if not data:
        return jsonify({"success": False, "message": "Invalid JSON data"}), 400

    playlist_name = data.get("playlist_name")
    plugin_id = data.get("plugin_id")
    plugin_instance = data.get("plugin_instance")

    try:
        playlist = playlist_manager.get_playlist(playlist_name)
        if not playlist:
            return jsonify({"success": False, "message": "Playlist not found"}), 400

        result = playlist.delete_plugin(plugin_id, plugin_instance)
        if not result:
            return jsonify({"success": False, "message": "Plugin instance not found"}), 400

        # save changes to device config file
        device_config.write_config()

    except Exception as e:
        logger.exception("EXCEPTION CAUGHT: " + str(e))
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500

    return jsonify({"success": True, "message": "Deleted plugin instance."})

@plugin_bp.route('/update_plugin_instance/<string:instance_name>', methods=['PUT'])
def update_plugin_instance(instance_name):
    device_config = current_app.config['DEVICE_CONFIG']
    playlist_manager = device_config.get_playlist_manager()

    try:
        form_data = parse_form(request.form)

        if not instance_name:
            raise RuntimeError("Instance name is required")
        plugin_settings = form_data
        plugin_settings.update(handle_request_files(request.files, request.form))

        plugin_id = plugin_settings.pop("plugin_id")
        plugin_instance = playlist_manager.find_plugin(plugin_id, instance_name)
        if not plugin_instance:
            return jsonify({"error": f"Plugin instance: {instance_name} does not exist"}), 500

        plugin_instance.settings = plugin_settings
        device_config.write_config()
    except Exception as e:
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500
    return jsonify({"success": True, "message": f"Updated plugin instance {instance_name}."})

@plugin_bp.route('/display_plugin_instance', methods=['POST'])
def display_plugin_instance():
    device_config = current_app.config['DEVICE_CONFIG']
    refresh_task = current_app.config['REFRESH_TASK']
    playlist_manager = device_config.get_playlist_manager()

    data = request.json
    if not data:
        return jsonify({"success": False, "message": "Invalid JSON data"}), 400

    playlist_name = data.get("playlist_name")
    plugin_id = data.get("plugin_id")
    plugin_instance_name = data.get("plugin_instance")

    try:
        playlist = playlist_manager.get_playlist(playlist_name)
        if not playlist:
            return jsonify({"success": False, "message": f"Playlist {playlist_name} not found"}), 400

        plugin_instance = playlist.find_plugin(plugin_id, plugin_instance_name)
        if not plugin_instance:
            return jsonify({"success": False, "message": f"Plugin instance '{plugin_instance_name}' not found"}), 400

        refresh_task.manual_update(PlaylistRefresh(playlist, plugin_instance, force=True))
    except Exception as e:
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500

    return jsonify({"success": True, "message": "Display updated"}), 200

@plugin_bp.route('/update_now', methods=['POST'])
def update_now():
    device_config = current_app.config['DEVICE_CONFIG']
    refresh_task = current_app.config['REFRESH_TASK']
    display_manager = current_app.config['DISPLAY_MANAGER']

    try:
        plugin_settings = parse_form(request.form)
        plugin_settings.update(handle_request_files(request.files))
        plugin_id = plugin_settings.pop("plugin_id")

        # Check if refresh task is running
        if refresh_task.running:
            refresh_task.manual_update(ManualRefresh(plugin_id, plugin_settings))
        else:
            # In development mode, directly update the display
            logger.info("Refresh task not running, updating display directly")
            plugin_config = device_config.get_plugin(plugin_id)
            if not plugin_config:
                return jsonify({"error": f"Plugin '{plugin_id}' not found"}), 404
                
            plugin = get_plugin_instance(plugin_config)
            image = plugin.generate_image(plugin_settings, device_config)
            display_manager.display_image(image, image_settings=plugin_config.get("image_settings", []))
            
    except Exception as e:
        logger.exception(f"Error in update_now: {str(e)}")
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500

    return jsonify({"success": True, "message": "Display updated"}), 200

@plugin_bp.route('/save_plugin_settings', methods=['POST'])
def save_plugin_settings():
    device_config = current_app.config['DEVICE_CONFIG']
    playlist_manager = device_config.get_playlist_manager()

    try:
        plugin_settings = parse_form(request.form)
        plugin_settings.update(handle_request_files(request.files))
        plugin_id = plugin_settings.pop("plugin_id")

        # Use "Default" playlist, create it if it doesn't exist
        default_playlist_name = "Default"
        playlist = playlist_manager.get_playlist(default_playlist_name)
        if not playlist:
            playlist_manager.add_playlist(default_playlist_name)
            playlist = playlist_manager.get_playlist(default_playlist_name)

        # Create a default instance name for this plugin
        instance_name = f"{plugin_id}_saved_settings"

        # Check if instance already exists
        existing_instance = playlist.find_plugin(plugin_id, instance_name)
        if existing_instance:
            # Update existing instance
            existing_instance.settings = plugin_settings
        else:
            # Create new instance
            plugin_dict = {
                "plugin_id": plugin_id,
                "refresh": {"interval": 3600},  # Default to 1 hour
                "plugin_settings": plugin_settings,
                "name": instance_name
            }
            playlist.add_plugin(plugin_dict)

        device_config.write_config()

        return jsonify({
            "success": True,
            "message": f"Settings saved to {default_playlist_name} playlist",
            "instance_name": instance_name
        }), 200

    except Exception as e:
        logger.exception(f"Error saving plugin settings: {str(e)}")
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500