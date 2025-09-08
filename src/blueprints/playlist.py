import json
import logging
from datetime import datetime, timedelta

from flask import Blueprint, current_app, jsonify, render_template, request, has_app_context

from utils.app_utils import handle_request_files, parse_form
from utils.http_utils import json_error, json_internal_error, json_success
from utils.time_utils import calculate_seconds, now_device_tz
from refresh_task import PlaylistRefresh

logger = logging.getLogger(__name__)
playlist_bp = Blueprint("playlist", __name__)

# Simple in-memory cache for ETA computations (per playlist, per-minute)
_eta_cache: dict[str, tuple[datetime, dict[str, dict]]] = {}


@playlist_bp.route("/add_plugin", methods=["POST"])
def add_plugin():
    device_config = current_app.config["DEVICE_CONFIG"]
    playlist_manager = device_config.get_playlist_manager()

    try:
        plugin_settings = parse_form(request.form)
        refresh_settings = json.loads(plugin_settings.pop("refresh_settings"))
        plugin_id = plugin_settings.pop("plugin_id")

        playlist = refresh_settings.get("playlist")
        instance_name = refresh_settings.get("instance_name")
        if not playlist:
            return json_error("Playlist name is required", status=400)
        if not instance_name or not instance_name.strip():
            return json_error("Instance name is required", status=400)
        if not all(
            char.isalpha() or char.isspace() or char.isnumeric()
            for char in instance_name
        ):
            return json_error(
                "Instance name can only contain alphanumeric characters and spaces",
                status=400,
            )
        refresh_type = refresh_settings.get("refreshType")
        if not refresh_type or refresh_type not in ["interval", "scheduled"]:
            return json_error("Refresh type is required", status=400)

        existing = playlist_manager.find_plugin(plugin_id, instance_name)
        if existing:
            return json_error(
                f"Plugin instance '{instance_name}' already exists", status=400
            )

        if refresh_type == "interval":
            unit, interval = refresh_settings.get("unit"), refresh_settings.get(
                "interval"
            )
            if not unit or unit not in ["minute", "hour", "day"]:
                return json_error("Refresh interval unit is required", status=400)
            if not interval:
                return json_error("Refresh interval is required", status=400)
            refresh_interval_seconds = calculate_seconds(int(interval), unit)
            refresh_config = {"interval": refresh_interval_seconds}
        else:
            refresh_time = refresh_settings.get("refreshTime")
            if not refresh_settings.get("refreshTime"):
                return json_error("Refresh time is required", status=400)
            refresh_config = {"scheduled": refresh_time}

        plugin_settings.update(handle_request_files(request.files))
        plugin_dict = {
            "plugin_id": plugin_id,
            "refresh": refresh_config,
            "plugin_settings": plugin_settings,
            "name": instance_name,
        }
        result = playlist_manager.add_plugin_to_playlist(playlist, plugin_dict)
        if not result:
            return json_error("Failed to add to playlist", status=500)

        device_config.write_config()
    except Exception:
        return json_internal_error(
            "add plugin to playlist",
            details={
                "hint": "Validate inputs; ensure playlist exists and instance name isn’t duplicated.",
            },
        )
    return json_success("Scheduled refresh configured.")


@playlist_bp.route("/playlist")
def playlists():
    device_config = current_app.config["DEVICE_CONFIG"]
    playlist_manager = device_config.get_playlist_manager()
    refresh_info = device_config.get_refresh_info()

    # Include latest metrics for badge rendering
    metrics = None
    try:
        ri_obj = device_config.get_refresh_info()
        metrics = {
            "request_ms": getattr(ri_obj, "request_ms", None),
            "generate_ms": getattr(ri_obj, "generate_ms", None),
            "preprocess_ms": getattr(ri_obj, "preprocess_ms", None),
            "display_ms": getattr(ri_obj, "display_ms", None),
            "plugin_id": getattr(ri_obj, "plugin_id", None),
            "playlist": getattr(ri_obj, "playlist", None),
            "plugin_instance": getattr(ri_obj, "plugin_instance", None),
        }
    except Exception:
        metrics = None
    # compute device current time string and cycle info per playlist
    try:
        now = now_device_tz(device_config)
        now_str = now.strftime("%Y-%m-%d %H:%M:%S %Z")
        tz_off_min = int((now.utcoffset() or timedelta(0)).total_seconds() // 60)
    except Exception:
        now_str = ""
        tz_off_min = 0
    try:
        device_cycle_minutes = int(device_config.get_config("plugin_cycle_interval_seconds", default=3600) // 60)
    except Exception:
        device_cycle_minutes = 60

    # Build per-playlist timing metadata: cycle and next refresh (if active)
    try:
        ri_obj = device_config.get_refresh_info()
        last_dt = ri_obj.get_refresh_datetime() if hasattr(ri_obj, "get_refresh_datetime") else None
    except Exception:
        last_dt = None
    playlist_timing: dict[str, dict] = {}
    rotation_eta: dict[str, dict] = {}
    try:
        for pl in playlist_manager.playlists:
            cycle_sec = getattr(pl, "cycle_interval_seconds", None)
            cycle_min = int((cycle_sec or device_cycle_minutes * 60) // 60)
            item: dict = {"cycle_minutes": cycle_min, "next_in_minutes": None, "next_at": None}
            try:
                if last_dt and getattr(ri_obj, "playlist", None) == pl.name:
                    # compute next time
                    next_dt = last_dt + timedelta(minutes=cycle_min)
                    delta_min = int(max(0, (next_dt - now).total_seconds() // 60))
                    item["next_in_minutes"] = delta_min
                    try:
                        item["next_at"] = next_dt.strftime("%Y-%m-%d %H:%M")
                    except Exception:
                        item["next_at"] = None
                # Also compute rotation ETA for each plugin in this playlist
                try:
                    eta_for_pl: dict[str, dict] = {}
                    num = len(pl.plugins)
                    if num > 0:
                        # Determine the index that will be displayed on the next cycle
                        if pl.current_plugin_index is None:
                            next_index = 0
                        else:
                            try:
                                if not (0 <= pl.current_plugin_index < num):
                                    next_index = 0
                                else:
                                    next_index = (pl.current_plugin_index + 1) % num
                            except Exception:
                                next_index = 0
                        # Time until the next cycle tick for this playlist
                        try:
                            # If this playlist produced the last image, use last_dt; otherwise assume next tick is cycle_min from now
                            if last_dt and getattr(ri_obj, "playlist", None) == pl.name:
                                until_next_min = max(0, int((last_dt + timedelta(minutes=cycle_min) - now).total_seconds() // 60))
                            else:
                                until_next_min = cycle_min
                        except Exception:
                            until_next_min = cycle_min

                        for idx, inst in enumerate(pl.plugins):
                            steps = (idx - next_index + num) % num
                            total_min = until_next_min + steps * cycle_min
                            eta_dt = now + timedelta(minutes=total_min)
                            eta_for_pl[inst.name] = {
                                "minutes": total_min,
                                "at": eta_dt.strftime("%H:%M"),
                            }
                    rotation_eta[pl.name] = eta_for_pl
                except Exception:
                    rotation_eta[pl.name] = {}
            except Exception:
                pass
            playlist_timing[pl.name] = item
    except Exception:
        playlist_timing = {}

    return render_template(
        "playlist.html",
        playlist_config=playlist_manager.to_dict(),
        refresh_info=refresh_info.to_dict(),
        metrics=metrics,
        device_now=now_str,
        device_tz_offset_min=tz_off_min,
        device_cycle_minutes=device_cycle_minutes,
        playlist_timing=playlist_timing,
        rotation_eta=rotation_eta,
    )


@playlist_bp.route("/create_playlist", methods=["POST"])
def create_playlist():
    device_config = current_app.config["DEVICE_CONFIG"]
    playlist_manager = device_config.get_playlist_manager()

    data = request.json
    if data is None:
        return json_error("Invalid JSON data", status=400)
    playlist_name = data.get("playlist_name")
    start_time = data.get("start_time")
    end_time = data.get("end_time")

    if not playlist_name or not playlist_name.strip():
        return json_error("Playlist name is required", status=400)
    if not start_time or not end_time:
        return json_error("Start time and End time are required", status=400)
    if end_time <= start_time:
        return json_error("End time must be greater than start time", status=400)

    try:
        playlist = playlist_manager.get_playlist(playlist_name)
        if playlist:
            return json_error(
                f"Playlist with name '{playlist_name}' already exists", status=400
            )

        # Prevent overlapping time windows
        try:
            new_start = datetime.strptime(start_time, "%H:%M")
            new_end = datetime.strptime(end_time, "%H:%M") if end_time != "24:00" else datetime.strptime("00:00", "%H:%M") + timedelta(days=1)
            for pl in playlist_manager.playlists:
                if getattr(pl, 'name', '') == 'Default':
                    continue
                ps = datetime.strptime(pl.start_time, "%H:%M")
                pe = datetime.strptime(pl.end_time, "%H:%M") if pl.end_time != "24:00" else datetime.strptime("00:00", "%H:%M") + timedelta(days=1)
                # overlap if start < other_end and other_start < end
                if new_start < pe and ps < new_end:
                    return json_error("Playlist time range overlaps with existing playlist", status=400)
        except Exception:
            # best-effort, fallback to allow
            pass

        result = playlist_manager.add_playlist(playlist_name, start_time, end_time)
        if not result:
            return json_error("Failed to create playlist", status=500)

        # save changes to device config file
        device_config.write_config()

    except Exception as e:
        logger.exception("EXCEPTION CAUGHT: " + str(e))
        return json_internal_error(
            "create playlist",
            details={
                "hint": "Ensure unique name and valid time range; check config write permissions.",
            },
        )

    return json_success("Created new Playlist!")


@playlist_bp.route("/update_playlist/<string:playlist_name>", methods=["PUT"])
def update_playlist(playlist_name):
    device_config = current_app.config["DEVICE_CONFIG"]
    playlist_manager = device_config.get_playlist_manager()

    data = request.get_json()

    new_name = data.get("new_name")
    start_time = data.get("start_time")
    end_time = data.get("end_time")
    cycle_minutes = data.get("cycle_minutes")  # optional override
    if not new_name or not start_time or not end_time:
        return json_error("Missing required fields", status=400)
    if end_time <= start_time:
        return json_error("End time must be greater than start time", status=400)

    playlist = playlist_manager.get_playlist(playlist_name)
    if not playlist:
        return json_error(f"Playlist '{playlist_name}' does not exist", status=400)

    # Prevent overlapping (exclude the playlist being updated)
    try:
        new_start = datetime.strptime(start_time, "%H:%M")
        new_end = datetime.strptime(end_time, "%H:%M") if end_time != "24:00" else datetime.strptime("00:00", "%H:%M") + timedelta(days=1)
        for pl in playlist_manager.playlists:
            if pl.name == playlist_name:
                continue
            if getattr(pl, 'name', '') == 'Default':
                continue
            ps = datetime.strptime(pl.start_time, "%H:%M")
            pe = datetime.strptime(pl.end_time, "%H:%M") if pl.end_time != "24:00" else datetime.strptime("00:00", "%H:%M") + timedelta(days=1)
            if new_start < pe and ps < new_end:
                return json_error("Playlist time range overlaps with existing playlist", status=400)
    except Exception:
        pass

    result = playlist_manager.update_playlist(
        playlist_name, new_name, start_time, end_time
    )
    if not result:
        return json_error("Failed to delete playlist", status=500)
    # Apply cycle override if provided
    try:
        if cycle_minutes is not None:
            try:
                cm = int(cycle_minutes)
                playlist = playlist_manager.get_playlist(new_name)
                if playlist:
                    playlist.cycle_interval_seconds = max(0, cm) * 60
            except Exception:
                pass
    except Exception:
        pass
    device_config.write_config()

    return json_success(f"Updated playlist '{playlist_name}'!")


@playlist_bp.route("/delete_playlist/<string:playlist_name>", methods=["DELETE"])
def delete_playlist(playlist_name):
    device_config = current_app.config["DEVICE_CONFIG"]
    playlist_manager = device_config.get_playlist_manager()

    if not playlist_name:
        return json_error("Playlist name is required", status=400)

    playlist = playlist_manager.get_playlist(playlist_name)
    if not playlist:
        return json_error(f"Playlist '{playlist_name}' does not exist", status=400)

    playlist_manager.delete_playlist(playlist_name)
    device_config.write_config()

    return json_success(f"Deleted playlist '{playlist_name}'!")


@playlist_bp.route("/update_device_cycle", methods=["PUT"])
def update_device_cycle():
    device_config = current_app.config["DEVICE_CONFIG"]
    refresh_task = current_app.config["REFRESH_TASK"]
    data = request.get_json(silent=True) or {}
    minutes = data.get("minutes") or 0
    try:
        m = int(minutes)
        if m < 1 or m > 1440:
            return json_error("Minutes must be between 1 and 1440", status=400)
    except Exception:
        return json_error("Invalid minutes", status=400)
    try:
        device_config.update_value("plugin_cycle_interval_seconds", m * 60, write=True)
        try:
            refresh_task.signal_config_change()
        except Exception:
            pass
        return json_success("Device refresh cadence updated.")
    except Exception:
        return json_internal_error("update_device_cycle", details={"hint": "Check config write permissions."})


@playlist_bp.route("/reorder_plugins", methods=["POST"])
def reorder_plugins():
    device_config = current_app.config["DEVICE_CONFIG"]
    playlist_manager = device_config.get_playlist_manager()

    try:
        data = request.get_json(force=True, silent=False)
        playlist_name = data.get("playlist_name")
        ordered = data.get("ordered")  # list of {plugin_id, name}
        if not playlist_name or not isinstance(ordered, list):
            return json_error("playlist_name and ordered list are required", status=400)

        playlist = playlist_manager.get_playlist(playlist_name)
        if not playlist:
            return json_error(f"Playlist '{playlist_name}' not found", status=400)

        if not playlist.reorder_plugins(ordered):
            return json_error("Invalid order payload", status=400)

        device_config.write_config()
        return json_success("Reordered plugins")
    except Exception:
        return json_internal_error(
            "reorder plugins",
            details={"hint": "Validate payload shape and ensure playlist exists."},
        )


## snooze endpoint removed


# Trigger next eligible instance in a specific playlist immediately
@playlist_bp.route("/display_next_in_playlist", methods=["POST"])
def display_next_in_playlist():
    device_config = current_app.config["DEVICE_CONFIG"]
    refresh_task = current_app.config["REFRESH_TASK"]
    playlist_manager = device_config.get_playlist_manager()

    try:
        data = request.get_json(force=True, silent=False)
        playlist_name = data.get("playlist_name")
        if not playlist_name:
            return json_error("playlist_name required", status=400)

        playlist = playlist_manager.get_playlist(playlist_name)
        if not playlist:
            return json_error(f"Playlist '{playlist_name}' not found", status=400)

        # Determine current time and next eligible
        try:
            current_dt = now_device_tz(device_config)
        except Exception:
            current_dt = datetime.now()

        plugin_instance = playlist.get_next_eligible_plugin(current_dt)
        if not plugin_instance:
            return json_error("No eligible instance in playlist", status=400)

        refresh_task.manual_update(PlaylistRefresh(playlist, plugin_instance, force=True))

        # Include latest metrics from refresh info if available
        metrics = {}
        try:
            ri = device_config.get_refresh_info()
            metrics = {
                "request_ms": getattr(ri, "request_ms", None),
                "generate_ms": getattr(ri, "generate_ms", None),
                "preprocess_ms": getattr(ri, "preprocess_ms", None),
                "display_ms": getattr(ri, "display_ms", None),
            }
        except Exception:
            pass

        return json_success("Displayed next instance", metrics=metrics)
    except Exception:
        return json_internal_error("display next in playlist")

# removed toggle_only_fresh endpoint per product decision


@playlist_bp.route("/playlist/eta/<string:playlist_name>")
def playlist_eta(playlist_name: str):
    """Return per-instance ETA for the named playlist.

    Cached per minute to keep route lightweight.
    """
    device_config = current_app.config["DEVICE_CONFIG"]
    playlist_manager = device_config.get_playlist_manager()

    pl = playlist_manager.get_playlist(playlist_name)
    if not pl:
        return json_error(f"Playlist '{playlist_name}' not found", status=404)

    # Cache key is playlist name; invalidate once per minute
    try:
        now = now_device_tz(device_config)
    except Exception:
        now = datetime.now()
    floor_min = now.replace(second=0, microsecond=0)

    cached = _eta_cache.get(playlist_name)
    if cached and cached[0] == floor_min:
        return json_success("ok", eta=cached[1])

    # Compute ETA for this playlist only
    try:
        # Determine cycle in minutes
        try:
            device_cycle_minutes = int(
                device_config.get_config("plugin_cycle_interval_seconds", default=3600)
                // 60
            )
        except Exception:
            device_cycle_minutes = 60
        cycle_sec = getattr(pl, "cycle_interval_seconds", None)
        cycle_min = int((cycle_sec or device_cycle_minutes * 60) // 60)

        # Determine last refresh and which index is next
        try:
            ri_obj = device_config.get_refresh_info()
            last_dt = (
                ri_obj.get_refresh_datetime()
                if hasattr(ri_obj, "get_refresh_datetime")
                else None
            )
        except Exception:
            last_dt = None

        try:
            num = len(pl.plugins)
        except Exception:
            num = 0

        eta_map: dict[str, dict] = {}
        if num > 0:
            try:
                if pl.current_plugin_index is None:
                    next_index = 0
                else:
                    if not (0 <= pl.current_plugin_index < num):
                        next_index = 0
                    else:
                        next_index = (pl.current_plugin_index + 1) % num
            except Exception:
                next_index = 0

            try:
                if last_dt and getattr(ri_obj, "playlist", None) == playlist_name:
                    until_next_min = max(
                        0,
                        int(
                            (
                                last_dt + timedelta(minutes=cycle_min) - now
                            ).total_seconds()
                            // 60
                        ),
                    )
                else:
                    until_next_min = cycle_min
            except Exception:
                until_next_min = cycle_min

            for idx, inst in enumerate(pl.plugins):
                try:
                    steps = (idx - next_index + num) % num
                    total_min = until_next_min + steps * cycle_min
                    eta_dt = now + timedelta(minutes=total_min)
                    eta_map[inst.name] = {
                        "minutes": total_min,
                        "at": eta_dt.strftime("%H:%M"),
                    }
                except Exception:
                    continue

        _eta_cache[playlist_name] = (floor_min, eta_map)
        return json_success("ok", eta=eta_map)
    except Exception:
        return json_internal_error("compute playlist eta")


@playlist_bp.app_template_filter("format_relative_time")
def format_relative_time(iso_date_string):
    # Parse the input ISO date string
    dt = datetime.fromisoformat(iso_date_string)

    # Get the timezone from the parsed datetime
    if dt.tzinfo is None:
        raise ValueError("Input datetime doesn't have a timezone.")

    # Get the current time using the device's configured timezone, if available
    if has_app_context():
        try:
            now = now_device_tz(current_app.config["DEVICE_CONFIG"])  # timezone-aware
        except Exception:
            now = datetime.now(dt.tzinfo)
    else:
        now = datetime.now(dt.tzinfo)

    # Align the input datetime to the device timezone for consistent comparisons
    dt_local = dt.astimezone(now.tzinfo)
    delta = now - dt_local

    # Compute time difference
    diff_seconds = delta.total_seconds()
    diff_minutes = diff_seconds / 60

    # Define formatting
    time_format = "%I:%M %p"  # Example: 04:30 PM
    month_day_format = "%b %d at " + time_format  # Example: Feb 12 at 04:30 PM

    # Determine relative time string
    if diff_seconds < 120:
        return "just now"
    elif diff_minutes < 60:
        return f"{int(diff_minutes)} minutes ago"
    # Use rolling windows to avoid midnight boundary flakiness across TZs
    elif diff_seconds < 60 * 60 * 24:
        return "today at " + dt_local.strftime(time_format).lstrip("0")
    elif diff_seconds < 60 * 60 * 48:
        return "yesterday at " + dt_local.strftime(time_format).lstrip("0")
    else:
        return dt_local.strftime(month_day_format).replace(
            " 0", " "
        )  # Removes leading zero in day
