"""The ``/playlist`` page, its ``/playlists`` redirect and the
``format_relative_time`` template filter."""

from datetime import UTC, datetime, timedelta
from typing import Any, cast

from flask import current_app, has_app_context, redirect, render_template, url_for

from refresh_task.health import PluginHealthTracker
from utils.time_utils import now_device_tz

from ._common import playlist_bp
from ._schedule import (
    _compute_playlist_rotation_eta,
    _safe_next_index,
    _safe_until_next_min,
)


@playlist_bp.route("/playlists", methods=["GET"])
def playlists_redirect() -> Any:
    return redirect(url_for("playlist.playlists"))


@playlist_bp.route("/playlist", methods=["GET"])
def playlists() -> Any:
    device_config = current_app.config["DEVICE_CONFIG"]
    playlist_manager = device_config.get_playlist_manager()
    refresh_info = device_config.get_refresh_info()
    plugins_list = device_config.get_plugins()

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
        device_cycle_minutes = int(
            int(device_config.get_config("plugin_cycle_interval_seconds", default=3600))
            // 60
        )
    except Exception:
        device_cycle_minutes = 60

    # Build per-playlist timing metadata: cycle and next refresh (if active)
    try:
        ri_obj = device_config.get_refresh_info()
        last_dt = (
            ri_obj.get_refresh_datetime()
            if hasattr(ri_obj, "get_refresh_datetime")
            else None
        )
    except Exception:
        last_dt = None
    playlist_timing: dict[str, dict[str, int | str | None]] = {}
    rotation_eta: dict[str, dict[str, dict[str, int | str]]] = {}
    try:
        for pl in playlist_manager.playlists:
            cycle_sec = getattr(pl, "cycle_interval_seconds", None)
            cycle_min = int(
                (int(cycle_sec) if cycle_sec else device_cycle_minutes * 60) // 60
            )
            item: dict[str, int | str | None] = {
                "cycle_minutes": cycle_min,
                "next_in_minutes": None,
                "next_at": None,
            }
            try:
                is_active = bool(
                    last_dt and getattr(ri_obj, "playlist", None) == pl.name
                )
                if is_active:
                    # compute next time
                    next_dt = cast(datetime, last_dt) + timedelta(minutes=cycle_min)
                    delta_min = int(max(0, (next_dt - now).total_seconds() // 60))
                    item["next_in_minutes"] = delta_min
                    try:
                        item["next_at"] = next_dt.strftime("%Y-%m-%d %H:%M")
                    except Exception:
                        item["next_at"] = None
                # Also compute rotation ETA for each plugin in this playlist
                try:
                    num = len(pl.plugins)
                    next_index = _safe_next_index(pl, num)
                    until_next_min = _safe_until_next_min(
                        is_active, cast(datetime | None, last_dt), cycle_min, now
                    )
                    rotation_eta[pl.name] = _compute_playlist_rotation_eta(
                        pl, next_index, until_next_min, cycle_min, now
                    )
                except Exception:
                    rotation_eta[pl.name] = {}
            except Exception:
                pass
            playlist_timing[pl.name] = item
    except Exception:
        playlist_timing = {}

    try:
        paused_status = _paused_status(playlist_manager, now_device_tz(device_config))
    except Exception:
        paused_status = {}

    return render_template(
        "playlist.html",
        paused_status=paused_status,
        playlist_config=playlist_manager.to_dict(),
        refresh_info=refresh_info.to_dict(),
        plugins={p["id"]: p for p in plugins_list},
        metrics=metrics,
        now_str=now_str,
        tz_off_min=tz_off_min,
        device_cycle_minutes=device_cycle_minutes,
        playlist_timing=playlist_timing,
        rotation_eta=rotation_eta,
        active_nav="playlists",
    )


@playlist_bp.app_template_filter("format_relative_time")
def format_relative_time(iso_date_string: str) -> str:
    # Parse the input ISO date string
    dt = datetime.fromisoformat(iso_date_string)

    # Get the timezone from the parsed datetime
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)

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
    if diff_minutes < 60:
        return f"{int(diff_minutes)} minutes ago"
    # Bucket by local calendar date, not elapsed time: a rolling 24h window
    # labels 8 PM last night as "today at 8:00 PM" when viewed at 2 AM.
    days_ago = (now.date() - dt_local.date()).days
    if days_ago <= 0:
        return "today at " + dt_local.strftime(time_format).lstrip("0")
    if days_ago == 1:
        return "yesterday at " + dt_local.strftime(time_format).lstrip("0")
    return dt_local.strftime(month_day_format).replace(
        " 0", " "
    )  # Removes leading zero in day


def _paused_status(playlist_manager: Any, now: datetime) -> dict[str, dict[str, str]]:
    """Map playlist name -> paused instance name -> short "Paused" label.

    A circuit-breaker pause is otherwise invisible on this page; the label says
    when the automatic retry will happen so a glance explains a missing plugin.
    """
    status: dict[str, dict[str, str]] = {}
    for pl in getattr(playlist_manager, "playlists", []):
        for inst in getattr(pl, "plugins", []):
            if not getattr(inst, "paused", False):
                continue
            label = "Paused"
            retry_at = PluginHealthTracker.next_probe_at(inst, now)
            if retry_at is not None:
                if retry_at <= now:
                    label = "Paused — retrying on its next turn"
                else:
                    local = retry_at.astimezone(now.tzinfo)
                    label = f"Paused — retrying at {local.strftime('%H:%M')}"
            status.setdefault(pl.name, {})[inst.name] = label
    return status
