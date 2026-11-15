import logging
import math
import os
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from uuid import uuid4

from flask import (
    Blueprint,
    current_app,
    jsonify,
    render_template,
    request,
    send_file,
    send_from_directory,
)
from flask.typing import ResponseReturnValue

from benchmarks.benchmark_storage import save_refresh_event, save_stage_event
from refresh_task import schedule
from refresh_task.health import PluginHealthTracker
from utils import blackout
from utils.api_responses import APIError, JsonResponse, json_error, json_success
from utils.backend_errors import mapped_render_errors
from utils.display_names import (
    friendly_instance_label,
    instance_suffix_label,
    is_auto_instance_name,
)
from utils.image_serving import maybe_serve_webp
from utils.output_validator import fit_image_to_device
from utils.rate_limit import CooldownLimiter
from utils.request_models import parse_plugin_order_request
from utils.time_utils import now_device_tz

logger = logging.getLogger(__name__)

main_bp = Blueprint("main", __name__)


def _playlist_cycle_seconds(device_config: Any, playlist_name: Any) -> float:
    """The cycle the refresh loop uses for *playlist_name*, in seconds."""
    device_interval = schedule.device_interval_seconds(device_config)
    if not playlist_name:
        return device_interval

    try:
        playlist_manager = device_config.get_playlist_manager()
        playlist = playlist_manager.get_playlist(playlist_name)
        return schedule.effective_cycle_seconds(playlist, device_interval)
    except Exception:
        logger.warning(
            "Playlist %r has an unreadable cycle interval; using the device's",
            playlist_name,
            exc_info=True,
        )
        return device_interval


def _loop_last_attempt() -> datetime | None:
    return schedule.last_attempt_of(current_app.config.get("REFRESH_TASK"))


def _parse_refresh_datetime(iso_value: Any) -> datetime | None:
    if not iso_value:
        return None
    try:
        dt = datetime.fromisoformat(iso_value)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _format_next_refresh_relative(next_dt: datetime, now_dt: datetime) -> str:
    diff_seconds = max(0, int(math.ceil((next_dt - now_dt).total_seconds())))
    if diff_seconds <= 30:
        return "Due now"
    if diff_seconds < 60:
        return f"in {diff_seconds}s"

    diff_minutes = math.ceil(diff_seconds / 60)
    if diff_minutes < 60:
        return f"in {diff_minutes}m"

    hours, minutes = divmod(diff_minutes, 60)
    if hours < 24:
        if minutes:
            return f"in {hours}h {minutes}m"
        return f"in {hours}h"

    local_dt = next_dt.astimezone(now_dt.tzinfo)
    return "at " + local_dt.strftime("%I:%M %p").lstrip("0")


def _build_next_refresh_meta(
    next_dt: datetime | None, cycle_minutes: int, now_dt: datetime
) -> str:
    parts: list[str] = []
    if next_dt:
        local_dt = next_dt.astimezone(now_dt.tzinfo)
        parts.append(f"ETA {local_dt.strftime('%I:%M %p').lstrip('0')}")
    if cycle_minutes:
        parts.append(f"Every {cycle_minutes} min")
    parts.append("auto")
    return " · ".join(parts)


def _annotate_refresh_schedule(
    payload: Any, device_config: Any, last_attempt: datetime | None = None
) -> Any:
    """Attach next-refresh timing metadata for dashboard rendering.

    ``last_attempt`` is when the refresh loop last acted on a due refresh
    (:func:`refresh_task.schedule.last_attempt_of`).
    """
    if not isinstance(payload, dict):
        return payload

    now_dt = now_device_tz(device_config)
    cycle_seconds = _playlist_cycle_seconds(device_config, payload.get("playlist"))
    cycle_minutes = schedule.cycle_minutes(cycle_seconds)
    payload["cycle_minutes"] = cycle_minutes

    refresh_dt = _parse_refresh_datetime(payload.get("refresh_time"))
    if not refresh_dt:
        payload["next_refresh_time"] = None
        payload["next_refresh_relative"] = None
        payload["next_refresh_meta"] = _build_next_refresh_meta(
            None, cycle_minutes, now_dt
        )
        return payload

    # The loop's own rule: a cycle after the last refresh or the last attempt,
    # so a failed or skipped refresh doesn't read "Due now" for a whole cycle.
    next_dt = schedule.next_due_at(
        refresh_dt.astimezone(now_dt.tzinfo),
        last_attempt,
        cycle_seconds,
        now_dt,
    )
    payload["next_refresh_time"] = next_dt.isoformat()
    payload["next_refresh_relative"] = _format_next_refresh_relative(next_dt, now_dt)
    payload["next_refresh_meta"] = _build_next_refresh_meta(
        next_dt, cycle_minutes, now_dt
    )
    return payload


def _peek_next_up(device_config: Any, current_dt: datetime) -> dict[str, Any]:
    """What the refresh loop would show next, without touching the playlist.

    Mirrors ``_determine_next_plugin_locked`` in ``refresh_task.loop_scheduling``:
    the next show-eligible instance, skipping circuit-breaker-paused instances
    unless their retry probe is due. The peek never writes
    ``current_plugin_index``, so it needs no config lock and cannot undo an
    advance the refresh thread makes meanwhile (B4).
    """
    playlist = device_config.get_playlist_manager().determine_active_playlist(
        current_dt
    )
    if not playlist:
        return {}

    def _paused_and_resting(inst: Any) -> bool:
        return bool(getattr(inst, "paused", False)) and not (
            PluginHealthTracker.probe_due(inst, current_dt)
        )

    inst = playlist.peek_next_eligible_plugin(current_dt, skip=_paused_and_resting)
    if not inst:
        return {}
    return {
        "playlist": playlist.name,
        "plugin_id": inst.plugin_id,
        "plugin_instance": inst.name,
    }


def _is_dev_mode() -> bool:
    env = (os.getenv("INKYPI_ENV") or os.getenv("FLASK_ENV") or "").strip().lower()
    return env in {"dev", "development"}


@main_bp.route("/", methods=["GET"])
def main_page() -> ResponseReturnValue:
    device_config = current_app.config["DEVICE_CONFIG"]
    playlist_manager = device_config.get_playlist_manager()
    # Compute a non-mutating next-up preview for SSR convenience
    current_dt = now_device_tz(device_config)

    try:
        next_up = _peek_next_up(device_config, current_dt)
    except Exception:
        next_up = {}

    # Determine whether a preview image exists (processed preferred, then current)
    has_preview = os.path.exists(device_config.processed_image_file) or os.path.exists(
        device_config.current_image_file
    )

    device_cycle_minutes = schedule.cycle_minutes(
        schedule.device_interval_seconds(device_config)
    )
    # Mirror /refresh-info's degrade-to-{} behaviour so a broken or missing
    # refresh info file cannot 500 the dashboard shell. The template guards
    # against empty refresh_info with `| default({})` helpers, so an empty
    # mapping is a safe render-time fallback.
    try:
        refresh_info = device_config.get_refresh_info().to_dict()
    except Exception:
        logger.exception("Failed to load refresh info for dashboard")
        refresh_info = {}
    else:
        _annotate_instance_labels(refresh_info)
        _annotate_refresh_schedule(refresh_info, device_config, _loop_last_attempt())

    return render_template(
        "inky.html",
        config=device_config.get_config(),
        plugins=device_config.get_plugins(),
        refresh_info=refresh_info,
        next_up=next_up,
        has_preview=has_preview,
        playlists=playlist_manager.playlists,
        active_playlist_name=playlist_manager.active_playlist,
        device_cycle_minutes=device_cycle_minutes,
        blackout=blackout.get_state(device_config),
        active_nav="dashboard",
    )


@main_bp.route("/preview", methods=["GET"])
def preview_image() -> ResponseReturnValue:
    device_config = current_app.config["DEVICE_CONFIG"]
    # Prefer processed image; fall back to current raw image if missing
    path = device_config.processed_image_file
    if not os.path.exists(path):
        path = device_config.current_image_file
    if not os.path.exists(path):
        return ("Preview not available", 404)
    # Both candidate paths come from device_config (trusted JSON).
    abs_path = os.path.abspath(path)
    safe_root = os.path.dirname(abs_path)
    filename = os.path.basename(abs_path)
    return maybe_serve_webp(safe_root, filename, request.headers.get("Accept"))


@main_bp.route("/dev/mock-frame", methods=["GET"])
def dev_mock_frame() -> ResponseReturnValue:
    """Serve the latest simulated mock-display frame in dev mode only."""
    if not _is_dev_mode():
        return ("Not found", 404)

    display_manager = current_app.config.get("DISPLAY_MANAGER")
    display = getattr(display_manager, "display", None)
    frame_path = getattr(display, "mock_frame_path", None)
    if not frame_path:
        return ("Mock frame not available", 404)

    abs_path = os.path.abspath(frame_path)
    if not os.path.exists(abs_path):
        return ("Mock frame not available", 404)

    safe_root = os.path.dirname(abs_path)
    filename = os.path.basename(abs_path)
    return send_from_directory(
        safe_root, filename, mimetype="image/png", as_attachment=False
    )


@main_bp.route("/api/screenshot", methods=["GET"])
def screenshot() -> ResponseReturnValue:
    """Return the current display image as PNG or WebP (JTN-450).

    Prefer the processed image; fall back to current_image_file.  Supports
    content negotiation via the Accept header (WebP when advertised), conditional
    GET via If-Modified-Since / 304, and sets Cache-Control: no-cache so
    monitoring dashboards always poll for fresh content.
    """
    device_config = current_app.config["DEVICE_CONFIG"]
    path = device_config.processed_image_file
    if not os.path.exists(path):
        path = device_config.current_image_file
    if not os.path.exists(path):
        return json_error("No display image available yet", status=404)

    abs_path = os.path.abspath(path)

    # Conditional GET — If-Modified-Since
    file_mtime = int(os.path.getmtime(abs_path))
    last_modified = datetime.fromtimestamp(file_mtime, tz=UTC)
    last_modified_str = last_modified.strftime("%a, %d %b %Y %H:%M:%S GMT")

    if_modified_since = request.headers.get("If-Modified-Since")
    if if_modified_since:
        try:
            client_mtime = parsedate_to_datetime(if_modified_since)
            if int(client_mtime.timestamp()) >= file_mtime:
                return "", 304
        except (ValueError, OSError):
            pass

    safe_root = os.path.dirname(abs_path)
    filename = os.path.basename(abs_path)
    response = maybe_serve_webp(safe_root, filename, request.headers.get("Accept"))
    response.headers["Last-Modified"] = last_modified_str
    response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


@main_bp.route("/api/current_image", methods=["GET"])
def get_current_image() -> ResponseReturnValue:
    """Serve current_image.png with conditional request support (If-Modified-Since) for polling."""
    device_config = current_app.config["DEVICE_CONFIG"]
    image_path = device_config.current_image_file

    if not os.path.exists(image_path):
        return json_error("Image not found", status=404)

    # Get the file's last modified time (UTC, truncated to seconds to match HTTP precision)
    file_mtime = int(os.path.getmtime(image_path))
    last_modified = datetime.fromtimestamp(file_mtime, tz=UTC)

    # Check If-Modified-Since header
    if_modified_since = request.headers.get("If-Modified-Since")
    if if_modified_since:
        try:
            # Parse the If-Modified-Since header (always returns timezone-aware datetime)
            client_mtime = parsedate_to_datetime(if_modified_since)
            client_mtime_seconds = int(client_mtime.timestamp())

            # Compare (both now in seconds, no sub-second precision)
            if client_mtime_seconds >= file_mtime:
                # File hasn't been modified since client's cached version
                return "", 304  # Not Modified
        except (ValueError, OSError):
            pass  # If parsing fails, proceed to send the file

    # Send the image with Last-Modified header
    response = send_file(image_path, mimetype="image/png")
    response.headers["Last-Modified"] = last_modified.strftime(
        "%a, %d %b %Y %H:%M:%S GMT"
    )
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Content-Disposition"] = (
        f'inline; filename="{os.path.basename(image_path)}"'
    )
    return response


def _plugin_display_name_map() -> dict[str, str]:
    """Return a {plugin_id: display_name} mapping for the current device config."""
    try:
        device_config = current_app.config["DEVICE_CONFIG"]
        return {
            p["id"]: p.get("display_name") or p["id"]
            for p in device_config.get_plugins()
        }
    except Exception:
        return {}


def _annotate_instance_labels(payload: Any) -> Any:
    """Attach friendly plugin/instance labels to a refresh-info-like dict.

    Adds ``plugin_display_name``, ``plugin_instance_label``, and
    ``plugin_instance_is_auto`` so the dashboard JS can render a friendly
    label without leaking the raw ``{plugin_id}_saved_settings`` key.
    """
    if not isinstance(payload, dict):
        return payload
    plugin_id = payload.get("plugin_id")
    instance_name = payload.get("plugin_instance")
    if plugin_id:
        display_map = _plugin_display_name_map()
        display_name = display_map.get(plugin_id) or plugin_id
        payload["plugin_display_name"] = display_name
        payload["plugin_instance_label"] = friendly_instance_label(
            instance_name, plugin_id, display_name
        )
        payload["plugin_instance_is_auto"] = is_auto_instance_name(
            instance_name, plugin_id
        )
    return payload


@main_bp.route("/refresh-info", methods=["GET"])
def refresh_info() -> ResponseReturnValue:
    device_config = current_app.config["DEVICE_CONFIG"]
    try:
        info = device_config.get_refresh_info().to_dict()
    except Exception:
        # Return an empty payload on failure — callers (dashboard JS and
        # unit tests in test_blueprint_coverage / test_startup_recovery) expect
        # `{}` rather than partial schedule metadata when refresh_info is
        # broken or missing.
        return jsonify({})
    _annotate_instance_labels(info)
    _annotate_refresh_schedule(info, device_config, _loop_last_attempt())
    return jsonify(info)


@main_bp.route("/next-up", methods=["GET"])
def next_up() -> ResponseReturnValue:
    device_config = current_app.config["DEVICE_CONFIG"]
    current_dt = now_device_tz(device_config)

    try:
        payload = _peek_next_up(device_config, current_dt)
        if not payload:
            return jsonify({})
        _annotate_instance_labels(payload)
        return jsonify(payload)
    except Exception:
        return jsonify({})


@main_bp.route("/api/plugin_order", methods=["POST"])
def save_plugin_order() -> ResponseReturnValue:
    """Save custom plugin order from dashboard drag-and-drop."""
    device_config = current_app.config["DEVICE_CONFIG"]
    parsed, parse_error = parse_plugin_order_request(request.get_json(silent=True))
    if parse_error is not None:
        return json_error(parse_error.message, status=parse_error.status)
    if parsed is None:
        return json_error("Invalid JSON payload", status=400)

    order = parsed.order
    registered_ids = {p["id"] for p in device_config.get_plugins()}
    if len(order) != len(set(order)):
        return json_error("Order must not contain duplicate plugin IDs", status=400)
    invalid_ids = [pid for pid in order if pid not in registered_ids]
    if invalid_ids:
        return json_error("Order contains unknown plugin IDs", status=400)
    missing_ids = registered_ids.difference(order)
    if missing_ids:
        return json_error(
            "Order must include every plugin ID exactly once",
            status=400,
        )
    device_config.set_plugin_order(order)
    return json_success()


@main_bp.route("/sw.js", methods=["GET"])
def service_worker() -> ResponseReturnValue:
    """Serve the service worker from the origin root.

    Service workers must be registered from the origin root to control all
    paths beneath it.  Flask's built-in /static/<filename> route would serve
    the file under /static/sw.js, which would limit its scope to /static/*.
    """
    static_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "static")
    )
    response = send_from_directory(
        static_dir, "sw.js", mimetype="application/javascript"
    )
    response.headers["Service-Worker-Allowed"] = "/"
    return response


# Serve static assets from src/static for test and dev environments
@main_bp.route("/static/<path:filename>", methods=["GET"])
def static_files(filename: str) -> ResponseReturnValue:
    try:
        static_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "static")
        )
        return send_from_directory(static_dir, filename)
    except Exception:
        return ("Not found", 404)


@main_bp.record
def _configure_app_static(state: Any) -> None:
    """Ensure Flask's built-in static route serves from src/static for tests/dev."""
    try:
        app = state.app
        static_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "static")
        )
        # Only adjust if directory exists
        if os.path.isdir(static_dir):
            app.static_folder = static_dir
            app.static_url_path = "/static"
    except Exception:
        # Best-effort; test client will fall back to blueprint route
        pass


_display_next_limiter = CooldownLimiter(10)


def _reset_display_next_cooldown() -> None:
    """Reset the display-next rate limiter. Exposed for testing."""
    _display_next_limiter.reset()


def _display_next_direct(
    device_config: Any,
    display_manager: Any,
    plugin_instance: Any,
    playlist: Any,
    current_dt: datetime,
    benchmark_id: str,
) -> tuple[int | None, JsonResponse | None]:
    """Execute a direct display update (dev path, no background task).

    Returns ``(generate_ms, error_response)``.  When *error_response* is not
    ``None`` it should be returned to the client immediately.
    """
    from time import perf_counter

    from plugins.plugin_registry import get_plugin_instance

    plugin_config = device_config.get_plugin(plugin_instance.plugin_id)
    if not plugin_config:
        return None, json_error("Plugin config not found", status=404)

    plugin = get_plugin_instance(plugin_config)
    _t_gen_start = perf_counter()
    try:
        image = plugin.generate_image(plugin_instance.settings, device_config)
    except RuntimeError:
        logger.exception("generate_image failed in display_next")
        return None, json_error("Plugin image generation failed", status=400)
    if image is None:
        # A control-only plugin legitimately produces no image (see BasePlugin.generate_image). That is a completed refresh with nothing to show, not a failure — leave the panel alone.
        logger.info(
            "display_next: %s produced no image; leaving the display unchanged",
            plugin_instance.plugin_id,
        )
        return None, json_error("Plugin produced no image to display", status=409)
    generate_ms = int((perf_counter() - _t_gen_start) * 1000)

    save_stage_event(device_config, benchmark_id, "generate_image", generate_ms)

    # Display — fitted to the panel exactly as the refresh task would.
    image = fit_image_to_device(image, device_config, plugin_instance.plugin_id)
    image_settings = plugin_config.get("image_settings", [])
    # One write. A TypeError here is a real driver/Pillow fault, so it must
    # propagate (500) rather than repeat the panel write and history entry.
    display_manager.display_image(
        image,
        image_settings=image_settings,
        history_meta={
            "refresh_type": "Playlist",
            "plugin_id": plugin_instance.plugin_id,
            "playlist": playlist.name,
            "plugin_instance": plugin_instance.name,
        },
    )

    from model import RefreshInfo

    latest = RefreshInfo(
        refresh_type="Playlist",
        plugin_id=plugin_instance.plugin_id,
        playlist=playlist.name,
        plugin_instance=plugin_instance.name,
        refresh_time=current_dt.isoformat(),
        image_hash=None,
        request_ms=None,
        display_ms=None,
        generate_ms=generate_ms,
        preprocess_ms=None,
        used_cached=False,
        benchmark_id=benchmark_id,
    )

    def _record_display(_config: dict[str, Any]) -> None:
        device_config.refresh_info = latest

    # Persist the advanced playlist index and the new refresh_info in one
    # locked transaction, so a concurrent update_atomic rollback in another
    # thread cannot discard either.
    device_config.update_atomic(_record_display)

    return generate_ms, None


def _gather_display_metrics(
    device_config: Any, generate_ms: int | None
) -> tuple[Any | None, Any | None, int | None, Any | None]:
    """Read timing metrics from refresh_info, filling in any gaps.

    Returns ``(request_ms, display_ms, generate_ms, preprocess_ms)``.
    """
    request_ms = display_ms = preprocess_ms = None
    try:
        ri = device_config.get_refresh_info()
        request_ms = getattr(ri, "request_ms", None)
        display_ms = getattr(ri, "display_ms", None)
        generate_ms = generate_ms or getattr(ri, "generate_ms", None)
        preprocess_ms = getattr(ri, "preprocess_ms", None)
    except Exception:
        logger.warning("Could not read this refresh's timings", exc_info=True)
    return request_ms, display_ms, generate_ms, preprocess_ms


def _persist_dev_refresh_event(
    device_config: Any,
    benchmark_id: str,
    plugin_instance: Any,
    playlist: Any,
    metrics: tuple[Any | None, Any | None, int | None, Any | None],
) -> None:
    """Persist a refresh event for the dev (direct) path."""
    request_ms, display_ms, generate_ms, preprocess_ms = metrics
    try:
        ri = device_config.get_refresh_info()
        cpu_percent = memory_percent = None
        try:
            import psutil

            cpu_percent = psutil.cpu_percent(interval=None)
            memory_percent = psutil.virtual_memory().percent
        except Exception:
            logger.debug("CPU and memory figures unavailable", exc_info=True)
        save_refresh_event(
            device_config,
            {
                "refresh_id": getattr(ri, "benchmark_id", benchmark_id),
                "ts": None,
                "plugin_id": plugin_instance.plugin_id,
                "instance": plugin_instance.name,
                "playlist": playlist.name,
                "used_cached": False,
                "request_ms": request_ms,
                "generate_ms": generate_ms,
                "preprocess_ms": getattr(ri, "preprocess_ms", None),
                "display_ms": getattr(ri, "display_ms", None),
                "cpu_percent": cpu_percent,
                "memory_percent": memory_percent,
                "notes": "display_next_dev",
            },
        )
    except Exception:
        logger.warning("Could not record this refresh's benchmark", exc_info=True)


@main_bp.route("/display-next", methods=["POST"])
def display_next() -> ResponseReturnValue:
    # Claim the cooldown before refreshing, not after: a refresh takes many
    # seconds on a Pi Zero, and a double click used to start two of them.
    allowed, retry_after = _display_next_limiter.acquire()
    if not allowed:
        remaining = math.ceil(retry_after)
        return json_error(
            f"Please wait {remaining}s before refreshing again.",
            status=429,
        )
    response = _show_next_plugin()
    if response[1] < 400:
        _display_next_limiter.record()  # the cooldown runs from the end
    else:
        _display_next_limiter.reset()  # a failed attempt costs no cooldown
    return response


def _show_next_plugin() -> JsonResponse:
    """Advance the active playlist and show its next plugin."""
    device_config = current_app.config["DEVICE_CONFIG"]
    refresh_task = current_app.config["REFRESH_TASK"]
    display_manager = current_app.config["DISPLAY_MANAGER"]
    playlist_manager = device_config.get_playlist_manager()

    # Determine current time
    current_dt = now_device_tz(device_config)

    # Pick next eligible and commit index change. The index advance is held
    # under the config lock so it cannot interleave with the refresh thread
    # or another request's update_atomic snapshot/rollback; it is persisted
    # by the refresh-info write that follows the display update.
    with device_config.locked():
        playlist = playlist_manager.determine_active_playlist(current_dt)
        plugin_instance = (
            playlist.get_next_eligible_plugin(current_dt) if playlist else None
        )
    if not playlist:
        return json_error("No active playlist", status=400)
    if not plugin_instance:
        return json_error("No eligible plugin to display", status=400)

    generate_ms = None
    update_metrics: dict[str, Any] | None = None
    benchmark_id = str(uuid4())
    via_refresh_task = bool(getattr(refresh_task, "running", False))
    try:
        if via_refresh_task:
            from refresh_task import PlaylistRefresh

            try:
                with mapped_render_errors("display_next", logger=logger):
                    update_metrics = refresh_task.manual_update(
                        PlaylistRefresh(playlist, plugin_instance, force=True)
                    )
            except RuntimeError:
                logger.exception("manual_update failed")
                return json_error("Plugin update failed", status=400)
        else:
            generate_ms, err = _display_next_direct(
                device_config,
                display_manager,
                plugin_instance,
                playlist,
                current_dt,
                benchmark_id,
            )
            if err:
                return err
    except APIError as exc:
        # A known failure (blackout, the loop stopping between the
        # ``running`` check and the enqueue, a timeout ...), mapped above.
        return json_error(
            exc.message, status=exc.status, code=exc.code, details=exc.details
        )
    except Exception:
        logger.exception("display_next failed")
        return json_error("An internal error occurred", status=500)

    if via_refresh_task:
        # This refresh's own timings; refresh_info may still describe the
        # previous one (see manual_update_timings). The loop records its own
        # benchmark row.
        from refresh_task import manual_update_timings

        return json_success(
            message="Display updated", metrics=manual_update_timings(update_metrics)
        )

    # The direct path wrote refresh_info itself, so it is current here, and
    # nobody else records the benchmark row.
    metrics = _gather_display_metrics(device_config, generate_ms)
    _persist_dev_refresh_event(
        device_config, benchmark_id, plugin_instance, playlist, metrics
    )
    request_ms, display_ms, generate_ms, preprocess_ms = metrics

    return json_success(
        message="Display updated",
        metrics={
            "request_ms": request_ms,
            "generate_ms": generate_ms,
            "preprocess_ms": preprocess_ms,
            "display_ms": display_ms,
        },
    )


@main_bp.route("/refresh", methods=["POST"])
def refresh_alias() -> ResponseReturnValue:
    """Backward-compatible alias for manual display advance."""
    return display_next()


# ---------------------------------------------------------------------------
# Jinja template filters for friendly plugin-instance display names.
# ---------------------------------------------------------------------------


@main_bp.app_template_filter("friendly_instance_label")
def _jinja_friendly_instance_label(instance_name: Any, plugin_id: Any = None) -> Any:
    """Jinja filter: return a friendly label for a plugin instance.

    Usage: ``{{ inst.name | friendly_instance_label(inst.plugin_id) }}``.
    Falls back to the plugin's ``display_name`` when the instance name is
    auto-generated.
    """
    display_name = _plugin_display_name_map().get(plugin_id) if plugin_id else None
    return friendly_instance_label(instance_name, plugin_id, display_name)


@main_bp.app_template_filter("instance_suffix_label")
def _jinja_instance_suffix_label(instance_name: Any, plugin_id: Any = None) -> str:
    """Jinja filter: return a parenthesised-suffix label, or empty string."""
    label = instance_suffix_label(instance_name, plugin_id)
    return label or ""


@main_bp.app_template_filter("is_auto_instance_name")
def _jinja_is_auto_instance_name(instance_name: Any, plugin_id: Any = None) -> bool:
    """Jinja filter: True when the instance name is the auto-generated key."""
    return bool(is_auto_instance_name(instance_name, plugin_id))
