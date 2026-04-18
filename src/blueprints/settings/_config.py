"""Settings pages, save, import/export, API keys, isolation, and safe-reset route handlers."""

import unicodedata
from zoneinfo import available_timezones

from flask import current_app, redirect, render_template, request

import blueprints.settings as _mod
from utils.http_utils import json_error, json_internal_error, json_success
from utils.time_utils import calculate_seconds

_DEVICE_NAME_MAX_LEN = 64


@_mod.settings_bp.route("/settings/isolation", methods=["GET", "POST", "DELETE"])
def plugin_isolation():
    device_config = current_app.config["DEVICE_CONFIG"]
    isolated = device_config.get_config("isolated_plugins", default=[])
    if not isinstance(isolated, list):
        isolated = []
    registered_ids = {plugin["id"] for plugin in device_config.get_plugins()}

    if request.method == "GET":
        return json_success(isolated_plugins=sorted(set(isolated)))

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return json_error("Request body must be a JSON object", status=400)
    plugin_id = body.get("plugin_id")
    if not isinstance(plugin_id, str) or not plugin_id.strip():
        return json_error(
            "plugin_id is required and must be a non-empty string",
            status=422,
            code="validation_error",
            details={"field": "plugin_id"},
        )
    normalized_plugin_id = plugin_id.strip()
    if normalized_plugin_id not in registered_ids:
        return json_error(
            "plugin_id must reference a registered plugin",
            status=422,
            code="validation_error",
            details={"field": "plugin_id"},
        )

    if request.method == "POST":
        if normalized_plugin_id not in isolated:
            isolated.append(normalized_plugin_id)
            device_config.update_value(
                "isolated_plugins", sorted(set(isolated)), write=True
            )
        return json_success(isolated_plugins=sorted(set(isolated)))

    # DELETE
    isolated = [p for p in isolated if p != normalized_plugin_id]
    device_config.update_value("isolated_plugins", sorted(set(isolated)), write=True)
    return json_success(isolated_plugins=sorted(set(isolated)))


@_mod.settings_bp.route("/settings/safe_reset", methods=["POST"])
def safe_reset():
    try:
        device_config = current_app.config["DEVICE_CONFIG"]
        config = device_config.get_config().copy()
        keep = {
            "playlist_config": config.get("playlist_config"),
            "plugins_enabled": config.get("plugins_enabled"),
            "name": config.get("name"),
            "timezone": config.get("timezone"),
            "time_format": config.get("time_format"),
            "display_type": config.get("display_type"),
            "resolution": config.get("resolution"),
            "orientation": config.get("orientation"),
            "preview_size_mode": config.get("preview_size_mode"),
        }
        # Reset selected runtime controls to safe defaults while preserving plugins/playlists.
        keep["plugin_cycle_interval_seconds"] = 3600
        keep["log_system_stats"] = False
        keep["isolated_plugins"] = []
        device_config.update_config(keep)
        return json_success(message="Safe reset applied.")
    except Exception as e:
        return json_internal_error("safe reset", details={"error": str(e)})


@_mod.settings_bp.route("/settings", methods=["GET"])
def settings_page():
    device_config = current_app.config["DEVICE_CONFIG"]
    timezones = sorted(available_timezones())
    return render_template(
        "settings.html", device_settings=device_config.get_config(), timezones=timezones
    )


@_mod.settings_bp.route("/settings/diagnostics", methods=["GET"])
def diagnostics_redirect():
    """Redirect /settings/diagnostics to the Diagnostics accordion on /settings.

    Diagnostics is an accordion embedded in the main settings page rather than
    a standalone page. Users who bookmark or follow direct links to
    ``/settings/diagnostics`` previously hit a 404 (JTN-627); redirect them to
    the anchor on the settings page instead.
    """
    return redirect("/settings#diagnostics", code=302)


@_mod.settings_bp.route("/settings/backup", methods=["GET"])
def backup_restore_page():
    device_config = current_app.config["DEVICE_CONFIG"]
    # For now, reuse the main settings page and anchor to a section; separate template can be added later
    return render_template(
        "settings.html",
        device_settings=device_config.get_config(),
        timezones=sorted(available_timezones()),
    )


def _include_export_keys() -> bool:
    """Allow keyed exports only on POST requests."""
    if request.method != "POST":
        return False

    body = request.get_json(silent=True)
    if isinstance(body, dict):
        value = body.get("include_keys")
    else:
        value = request.form.get("include_keys")

    if isinstance(value, bool):
        return value

    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


@_mod.settings_bp.route("/settings/export", methods=["GET"])
@_mod.settings_bp.route(
    "/settings/export", methods=["POST"], endpoint="export_settings_post"
)
def export_settings():
    try:
        include_keys = _include_export_keys()
        device_config = current_app.config["DEVICE_CONFIG"]

        # Build export object with config plus env keys when requested
        data = {
            "config": device_config.get_config(),
        }
        if include_keys:
            # Include known API keys and possibly other keys
            keys = {}
            for k in (
                "OPEN_AI_SECRET",
                "OPEN_WEATHER_MAP_SECRET",
                "NASA_SECRET",
                "UNSPLASH_ACCESS_KEY",
                "GITHUB_SECRET",
                "GOOGLE_AI_SECRET",
            ):
                try:
                    v = device_config.load_env_key(k)
                except Exception:
                    v = None
                if v:
                    keys[k] = v
            data["env_keys"] = keys

        # JSON response for now; a file download route can be added if needed
        return json_success(data=data)
    except Exception as e:
        _mod.logger.exception("Error exporting settings")
        return json_internal_error(
            "export settings",
            details={"hint": "Check config readability.", "error": str(e)},
        )


def _extract_import_payload():
    payload = None
    if request.is_json:
        payload = request.get_json(silent=True)
    if payload is None:
        file = request.files.get("file")
        if file:
            import json as _json

            try:
                payload = _json.loads(file.stream.read().decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return None
    if not payload or not isinstance(payload, dict):
        return None
    return payload


@_mod.settings_bp.route("/settings/import", methods=["POST"])
def import_settings():
    try:
        device_config = current_app.config["DEVICE_CONFIG"]
        # Accept JSON body or form upload with a JSON file
        payload = _extract_import_payload()
        if payload is None:
            return json_error("Invalid import payload", status=400)

        cfg = payload.get("config")
        if isinstance(cfg, dict):
            # Filter to allowed keys only
            filtered_cfg = {
                k: v for k, v in cfg.items() if k in _mod._ALLOWED_IMPORT_CONFIG_KEYS
            }
            device_config.update_config(filtered_cfg)

        env_keys = payload.get("env_keys") or {}
        if isinstance(env_keys, dict):
            for k, v in env_keys.items():
                if k not in _mod._ALLOWED_IMPORT_ENV_KEYS or v is None:
                    continue
                try:
                    device_config.set_env_key(k, str(v))
                except Exception:
                    _mod.logger.exception("Failed setting env key during import: %s", k)

        return json_success(message="Import completed")
    except Exception as e:
        _mod.logger.exception("Error importing settings")
        return json_internal_error(
            "import settings",
            details={
                "hint": "Verify JSON structure and file permissions.",
                "error": str(e),
            },
        )


@_mod.settings_bp.route("/settings/api-keys", methods=["GET"])
def api_keys_page():
    device_config = current_app.config["DEVICE_CONFIG"]

    def mask(value):
        if not value:
            return None
        try:
            if len(value) >= 4:
                return f"...{value[-4:]} ({len(value)} chars)"
            return f"set ({len(value)} chars)"
        except Exception:
            return "set"

    keys = {
        "OPEN_AI_SECRET": device_config.load_env_key("OPEN_AI_SECRET"),
        "OPEN_WEATHER_MAP_SECRET": device_config.load_env_key(
            "OPEN_WEATHER_MAP_SECRET"
        ),
        "NASA_SECRET": device_config.load_env_key("NASA_SECRET"),
        "UNSPLASH_ACCESS_KEY": device_config.load_env_key("UNSPLASH_ACCESS_KEY"),
        "GITHUB_SECRET": device_config.load_env_key("GITHUB_SECRET"),
        "GOOGLE_AI_SECRET": device_config.load_env_key("GOOGLE_AI_SECRET"),
    }
    masked = {k: mask(v) for k, v in keys.items()}
    api_key_plugins = {
        "OPEN_AI_SECRET": ["AI Image", "AI Text"],
        "OPEN_WEATHER_MAP_SECRET": ["Weather"],
        "NASA_SECRET": ["NASA APOD"],
        "UNSPLASH_ACCESS_KEY": ["Unsplash Background"],
        "GITHUB_SECRET": ["GitHub"],
        "GOOGLE_AI_SECRET": ["AI Image", "AI Text"],
    }
    return render_template(
        "api_keys.html",
        api_keys_mode="managed",
        entries=[],
        masked=masked,
        api_key_plugins=api_key_plugins,
    )


@_mod.settings_bp.route("/settings/save_api_keys", methods=["POST"])
def save_api_keys():
    device_config = current_app.config["DEVICE_CONFIG"]
    try:
        form_data = request.form.to_dict()
        updated = []
        skipped_placeholder = []
        for key in (
            "OPEN_AI_SECRET",
            "OPEN_WEATHER_MAP_SECRET",
            "NASA_SECRET",
            "UNSPLASH_ACCESS_KEY",
            "GITHUB_SECRET",
            "GOOGLE_AI_SECRET",
        ):
            value = form_data.get(key)
            if not value:
                # Empty field means "leave current key unchanged" (JTN-598).
                continue
            # Defense-in-depth against JTN-598: reject any value that is solely the
            # U+2022 BLACK CIRCLE placeholder. Historically the form pre-filled the
            # value attribute with literal bullet characters to fake a mask; if a
            # stale page (or anything else) POSTs that string back, we must not
            # overwrite the real key with bullets. Strip whitespace first so we
            # also catch values like "  ••••  " that a stale client could send.
            stripped = value.strip()
            if not stripped:
                # Whitespace-only input is treated the same as empty — keep
                # the existing key unchanged.
                continue
            if set(stripped) <= {"\u2022"}:
                _mod.logger.warning(
                    "Rejected save_api_keys value for %s: value is only U+2022 "
                    "placeholder characters (likely a stale cached page or a "
                    "client that appended to the legacy bullet pre-fill).",
                    key,
                )
                skipped_placeholder.append(key)
                continue
            device_config.set_env_key(key, value)
            updated.append(key)
        extra: dict = {"updated": updated}
        if skipped_placeholder:
            extra["skipped_placeholder"] = skipped_placeholder
        return json_success(message="API keys saved.", **extra)
    except Exception:
        _mod.logger.exception("Error saving API keys")
        return json_internal_error(
            "saving API keys",
            details={
                "hint": "Ensure .env is writable and values are valid; check disk space/permissions.",
            },
        )


@_mod.settings_bp.route("/settings/delete_api_key", methods=["POST"])
def delete_api_key():
    device_config = current_app.config["DEVICE_CONFIG"]
    key = request.form.get("key")
    valid_keys = {
        "OPEN_AI_SECRET",
        "OPEN_WEATHER_MAP_SECRET",
        "NASA_SECRET",
        "UNSPLASH_ACCESS_KEY",
        "GITHUB_SECRET",
        "GOOGLE_AI_SECRET",
    }
    if key not in valid_keys:
        return json_error("Invalid key name", status=400)
    try:
        device_config.unset_env_key(key)
        return json_success(message=f"Deleted {key}.")
    except Exception:
        _mod.logger.exception("Error deleting API key")
        return json_internal_error(
            "deleting API key",
            details={"hint": "Verify .env file permissions and key exists."},
        )


def _field_error(message, field):
    """Return a 422 validation error response for *field*."""
    return json_error(
        message,
        status=422,
        code="validation_error",
        details={"field": field},
    )


def _validate_interval(form_data):
    """Validate and return the parsed interval, or a JSON error response."""
    interval = form_data.get("interval")
    unit = form_data.get("unit")

    if not unit or unit not in ("minute", "hour"):
        return _field_error("Plugin cycle interval unit is required", "unit")
    if not interval or not interval.strip():
        return _field_error("Refresh interval is required", "interval")
    try:
        interval_int = int(interval)
    except (ValueError, TypeError):
        return _field_error("Refresh interval must be a number", "interval")
    if interval_int < 1:
        return _field_error("Refresh interval must be at least 1", "interval")

    plugin_cycle_interval_seconds = calculate_seconds(interval_int, unit)
    if plugin_cycle_interval_seconds > 86400 or plugin_cycle_interval_seconds <= 0:
        return _field_error(
            "Plugin cycle interval must be less than 24 hours", "interval"
        )
    return None


def _validate_device_name(form_data):
    """Validate device name length and control characters."""
    raw_device_name = form_data.get("deviceName", "")
    device_name = raw_device_name.strip()
    if not device_name:
        return _field_error("Device Name is required", "deviceName")
    if len(device_name) > _DEVICE_NAME_MAX_LEN:
        return _field_error(
            f"Device Name must be {_DEVICE_NAME_MAX_LEN} characters or fewer",
            "deviceName",
        )
    if any(unicodedata.category(ch) == "Cc" and ch != "\t" for ch in raw_device_name):
        return _field_error(
            "Device Name may not contain control characters",
            "deviceName",
        )
    return None


def _validate_enum_field(form_data, field, allowed, *, required=True):
    """Validate that *field* is one of *allowed* values.

    When *required* is True the field must be present and non-empty.
    When False the field is only checked if present.
    """
    value = form_data.get(field)
    if required:
        if not value or value not in allowed:
            return _field_error(
                f"{field} is required",
                field,
            )
    else:
        if value is not None and value not in allowed:
            return _field_error(
                f"{field} must be one of {', '.join(repr(a) for a in allowed)}",
                field,
            )
    return None


def _validate_image_settings(form_data):
    """Validate numeric image-adjustment fields in *form_data*."""
    import math

    _IMAGE_SETTING_MIN = 0.0
    _IMAGE_SETTING_MAX = 10.0
    for field in (
        "saturation",
        "brightness",
        "sharpness",
        "contrast",
        "inky_saturation",
    ):
        raw = form_data.get(field)
        if raw is None:
            continue
        try:
            value = float(raw)
        except (ValueError, TypeError):
            return _field_error(f"Invalid numeric value for {field}", field)
        if not math.isfinite(value):
            return _field_error(f"Invalid numeric value for {field}", field)
        if value < _IMAGE_SETTING_MIN or value > _IMAGE_SETTING_MAX:
            return _field_error(
                f"{field} must be between {_IMAGE_SETTING_MIN} and {_IMAGE_SETTING_MAX}",
                field,
            )
    return None


def _validate_settings_form(form_data):
    err = _validate_device_name(form_data)
    if err:
        return err

    err = _validate_interval(form_data)
    if err:
        return err

    # Timezone
    timezone_name = form_data.get("timezoneName")
    if not timezone_name:
        return _field_error("Time Zone is required", "timezoneName")
    if timezone_name not in available_timezones():
        return _field_error(
            "Time Zone must be a valid IANA timezone (e.g. UTC, America/New_York)",
            "timezoneName",
        )

    time_format = form_data.get("timeFormat")
    if not time_format or time_format not in ("12h", "24h"):
        return _field_error("Time format is required", "timeFormat")

    err = _validate_enum_field(
        form_data, "orientation", ("horizontal", "vertical"), required=False
    )
    if err:
        return err
    err = _validate_enum_field(
        form_data, "previewSizeMode", ("native", "scaled", "fit"), required=False
    )
    if err:
        return err

    return _validate_image_settings(form_data)


def _build_settings_dict(form_data):
    unit = form_data.get("unit")
    interval = form_data.get("interval")
    plugin_cycle_interval_seconds = calculate_seconds(int(interval), unit)

    settings = {
        "name": form_data.get("deviceName"),
        "orientation": form_data.get("orientation"),
        "inverted_image": form_data.get("invertImage") == "on",
        "log_system_stats": form_data.get("logSystemStats") == "on",
        "timezone": form_data.get("timezoneName"),
        "time_format": form_data.get("timeFormat"),
        "plugin_cycle_interval_seconds": plugin_cycle_interval_seconds,
        "image_settings": {
            "saturation": float(form_data.get("saturation", "1.0")),
            "brightness": float(form_data.get("brightness", "1.0")),
            "sharpness": float(form_data.get("sharpness", "1.0")),
            "contrast": float(form_data.get("contrast", "1.0")),
        },
        "preview_size_mode": form_data.get("previewSizeMode", "native"),
    }
    if "inky_saturation" in form_data:
        settings["image_settings"]["inky_saturation"] = float(
            form_data.get("inky_saturation", "0.5")
        )
    return settings, plugin_cycle_interval_seconds


@_mod.settings_bp.route("/save_settings", methods=["POST"])
def save_settings():
    device_config = current_app.config["DEVICE_CONFIG"]

    try:
        form_data = request.form.to_dict()

        error = _validate_settings_form(form_data)
        if error:
            return error

        previous_interval_seconds = device_config.get_config(
            "plugin_cycle_interval_seconds"
        )
        settings, plugin_cycle_interval_seconds = _build_settings_dict(form_data)
        device_config.update_config(settings)

        if plugin_cycle_interval_seconds != previous_interval_seconds:
            # wake the background thread up to signal interval config change
            refresh_task = current_app.config["REFRESH_TASK"]
            refresh_task.signal_config_change()
    except RuntimeError:
        return json_error(
            "An internal error occurred", status=500, code="internal_error"
        )
    except Exception:
        _mod.logger.exception("Error saving device settings")
        return json_internal_error(
            "saving device settings",
            details={"hint": "Check numeric values and config file permissions."},
        )
    return json_success(message="Saved settings.")


# Legacy route aliases used by older UI/tests.
@_mod.settings_bp.route("/settings/device", methods=["GET", "POST"])
def save_device_settings():
    if request.method == "GET":
        return settings_page()
    return save_settings()


@_mod.settings_bp.route("/settings/display", methods=["GET", "POST"])
def save_display_settings():
    if request.method == "GET":
        return settings_page()
    return save_settings()


@_mod.settings_bp.route("/settings/network", methods=["GET", "POST"])
def save_network_settings():
    if request.method == "GET":
        return settings_page()
    return save_settings()
