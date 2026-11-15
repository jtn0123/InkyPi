"""Settings pages, save, import/export, API keys, isolation, and safe-reset route handlers."""

import unicodedata
from typing import Any
from zoneinfo import available_timezones

from flask import current_app, redirect, render_template, request
from flask.typing import ResponseReturnValue

from app_setup.logging_setup import configure_log_timezone
from blueprints.settings import logger, settings_bp
from display.rendering_settings import SCREEN_RENDERING_KEY, SCREEN_RENDERING_MODES
from utils.api_responses import JsonResponse, json_error, json_success
from utils.backend_errors import ClientInputError, route_error_boundary
from utils.config_schema import ConfigValidationError
from utils.time_utils import calculate_seconds

_DEVICE_NAME_MAX_LEN = 64

# Import allowlists for settings import. ``refresh_info`` is left out on
# purpose: it records what this screen is showing right now, so restoring a
# backup's copy would make the dashboard describe a picture that isn't there.
_ALLOWED_IMPORT_CONFIG_KEYS = frozenset(
    {
        "name",
        "resolution",
        "orientation",
        "timezone",
        "color_mode",
        "playlist_config",
        "plugins",
        "plugin_cycle_interval_seconds",
        "time_format",
        "image_settings",
        "display_type",
        "preview_size_mode",
        "saved_settings",
        "inverted_image",
        "log_system_stats",
    }
)

# The provider keys plugins read; a keyed backup exports and imports exactly
# these, so a restore brings back every key a plugin needs.
_BACKUP_ENV_KEYS = frozenset(
    {
        "GITHUB_SECRET",
        "GOOGLE_AI_SECRET",
        "IMMICH_KEY",
        "NASA_SECRET",
        "OPEN_AI_SECRET",
        "OPEN_WEATHER_MAP_SECRET",
        "UNSPLASH_ACCESS_KEY",
    }
)


def _isolation_state() -> tuple[Any, list[Any], set[Any]]:
    device_config = current_app.config["DEVICE_CONFIG"]
    isolated = device_config.get_config("isolated_plugins", default=[])
    if not isinstance(isolated, list):
        isolated = []
    registered_ids = {plugin["id"] for plugin in device_config.get_plugins()}
    return device_config, isolated, registered_ids


def _validated_isolation_plugin_id(registered_ids: set[Any]) -> str:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ClientInputError("Request body must be a JSON object", status=400)
    plugin_id = body.get("plugin_id")
    if not isinstance(plugin_id, str) or not plugin_id.strip():
        raise ClientInputError(
            "plugin_id is required and must be a non-empty string",
            status=422,
            code="validation_error",
            field="plugin_id",
        )
    normalized_plugin_id = plugin_id.strip()
    if normalized_plugin_id not in registered_ids:
        raise ClientInputError(
            "plugin_id must reference a registered plugin",
            status=422,
            code="validation_error",
            field="plugin_id",
        )
    return normalized_plugin_id


def plugin_isolation() -> ResponseReturnValue:
    _, isolated, _ = _isolation_state()
    return json_success(isolated_plugins=sorted(set(isolated)))


def add_plugin_isolation() -> ResponseReturnValue:
    with route_error_boundary(
        "add plugin isolation",
        logger=logger,
        hint="Provide a valid registered plugin_id in a JSON object.",
    ):
        device_config, isolated, registered_ids = _isolation_state()
        normalized_plugin_id = _validated_isolation_plugin_id(registered_ids)

        if normalized_plugin_id not in isolated:
            isolated.append(normalized_plugin_id)
            device_config.update_value(
                "isolated_plugins", sorted(set(isolated)), write=True
            )
        return json_success(isolated_plugins=sorted(set(isolated)))


def remove_plugin_isolation() -> ResponseReturnValue:
    with route_error_boundary(
        "remove plugin isolation",
        logger=logger,
        hint="Provide a valid registered plugin_id in a JSON object.",
    ):
        device_config, isolated, registered_ids = _isolation_state()
        normalized_plugin_id = _validated_isolation_plugin_id(registered_ids)

        isolated = [p for p in isolated if p != normalized_plugin_id]
        device_config.update_value(
            "isolated_plugins", sorted(set(isolated)), write=True
        )
        return json_success(isolated_plugins=sorted(set(isolated)))


settings_bp.add_url_rule(
    "/settings/isolation", view_func=plugin_isolation, methods=["GET"]
)
settings_bp.add_url_rule(
    "/settings/isolation", view_func=add_plugin_isolation, methods=["POST"]
)
settings_bp.add_url_rule(
    "/settings/isolation", view_func=remove_plugin_isolation, methods=["DELETE"]
)


@settings_bp.route("/settings/safe_reset", methods=["POST"])
def safe_reset() -> ResponseReturnValue:
    with route_error_boundary(
        "safe reset",
        logger=logger,
        hint="Check config readability and write permissions.",
    ):
        device_config = current_app.config["DEVICE_CONFIG"]
        # Reset only these runtime controls. update_config merges, so every
        # other key (plugins, playlists, name, display) is left as it was;
        # copying them in here wrote null for any that had never been set,
        # which the config schema rejects at the next start.
        device_config.update_config(
            {
                "plugin_cycle_interval_seconds": 3600,
                "log_system_stats": False,
                "isolated_plugins": [],
            }
        )
        return json_success(message="Safe reset applied.")


@settings_bp.route("/settings", methods=["GET"])
def settings_page() -> ResponseReturnValue:
    device_config = current_app.config["DEVICE_CONFIG"]
    timezones = sorted(available_timezones())
    return render_template(
        "settings.html",
        device_settings=device_config.get_config(),
        timezones=timezones,
        active_nav="settings",
        pin_enabled=bool(current_app.config.get("AUTH_ENABLED")),
    )


@settings_bp.route("/settings/diagnostics", methods=["GET"])
def diagnostics_redirect() -> ResponseReturnValue:
    """Redirect /settings/diagnostics to the Diagnostics accordion on /settings.

    Diagnostics is an accordion embedded in the main settings page rather than
    a standalone page. Users who bookmark or follow direct links to
    ``/settings/diagnostics`` previously hit a 404 (JTN-627); redirect them to
    the anchor on the settings page instead.
    """
    return redirect("/settings#diagnostics", code=302)


@settings_bp.route("/settings/backup", methods=["GET"])
def backup_restore_page() -> ResponseReturnValue:
    device_config = current_app.config["DEVICE_CONFIG"]
    # For now, reuse the main settings page and anchor to a section; separate template can be added later
    return render_template(
        "settings.html",
        device_settings=device_config.get_config(),
        timezones=sorted(available_timezones()),
        active_nav="settings",
        pin_enabled=bool(current_app.config.get("AUTH_ENABLED")),
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


@settings_bp.route("/settings/export", methods=["GET"])
@settings_bp.route(
    "/settings/export", methods=["POST"], endpoint="export_settings_post"
)
def export_settings() -> ResponseReturnValue:
    with route_error_boundary(
        "export settings",
        logger=logger,
        hint="Check config readability.",
    ):
        include_keys = _include_export_keys()
        if include_keys and not current_app.config.get("AUTH_ENABLED"):
            # Without a PIN every page is open to the whole network, so a
            # keyed backup would hand every stored API key to any device on it.
            return json_error(
                "Set a PIN before including API keys in a backup. Without one, "
                "anyone on your network could download them.",
                status=403,
            )
        device_config = current_app.config["DEVICE_CONFIG"]

        # Build export object with config plus env keys when requested
        data = {
            "config": device_config.get_config(),
        }
        if include_keys:
            keys = {}
            for k in sorted(_BACKUP_ENV_KEYS):
                try:
                    v = device_config.load_env_key(k)
                except Exception:
                    v = None
                if v:
                    keys[k] = v
            data["env_keys"] = keys

        # JSON response for now; a file download route can be added if needed
        return json_success(data=data)


def _extract_import_payload() -> dict[str, Any] | None:
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
    return dict(payload)


def _apply_imported_config(device_config: Any, filtered_cfg: dict[str, Any]) -> None:
    """Write imported settings and rebuild the models they feed.

    Every config write serialises ``playlist_config`` from the in-memory
    playlist manager, so the manager must be rebuilt from the imported dict
    inside the same transaction or the write puts the old playlists back.
    """
    playlist_config = filtered_cfg.get("playlist_config")
    if "playlist_config" in filtered_cfg and not isinstance(playlist_config, dict):
        raise ClientInputError("Backup has an invalid playlist section", status=400)

    def apply(config: dict[str, Any]) -> None:
        config.update(filtered_cfg)
        if playlist_config is not None:
            try:
                device_config.playlist_manager = device_config.load_playlist_manager()
            except (AttributeError, KeyError, TypeError, ValueError) as exc:
                raise ClientInputError(
                    "Backup has an invalid playlist section", status=400
                ) from exc

    try:
        device_config.update_atomic(apply)
    except ConfigValidationError as exc:
        # Nothing was written; the rollback restored the running config.
        raise ClientInputError(
            f"Backup does not fit this device's settings: {exc}", status=400
        ) from exc

    if "timezone" in filtered_cfg:
        configure_log_timezone(device_config.get_config("timezone"))
    # The refresh loop keeps a snapshot of timezone, resolution and playlists;
    # rebuild it so the restored settings apply without a restart.
    refresh_task = current_app.config.get("REFRESH_TASK")
    if refresh_task is not None:
        try:
            refresh_task.signal_config_change()
        except Exception:
            logger.exception("Could not notify refresh task after import")


@settings_bp.route("/settings/import", methods=["POST"])
def import_settings() -> ResponseReturnValue:
    with route_error_boundary(
        "import settings",
        logger=logger,
        hint="Verify JSON structure and file permissions.",
    ):
        device_config = current_app.config["DEVICE_CONFIG"]
        # Accept JSON body or form upload with a JSON file
        payload = _extract_import_payload()
        if payload is None:
            raise ClientInputError("Invalid import payload", status=400)

        cfg_keys_applied = 0
        cfg = payload.get("config")
        if isinstance(cfg, dict):
            # Filter to allowed keys only
            filtered_cfg = {
                k: v for k, v in cfg.items() if k in _ALLOWED_IMPORT_CONFIG_KEYS
            }
            if filtered_cfg:
                _apply_imported_config(device_config, filtered_cfg)
                cfg_keys_applied = len(filtered_cfg)

        env_keys_applied = 0
        env_keys = payload.get("env_keys") or {}
        if isinstance(env_keys, dict):
            for k, v in env_keys.items():
                if k not in _BACKUP_ENV_KEYS or v is None:
                    continue
                try:
                    device_config.set_env_key(k, str(v))
                    env_keys_applied += 1
                except Exception:
                    logger.exception("Failed setting env key during import: %s", k)

        if cfg_keys_applied == 0 and env_keys_applied == 0:
            raise ClientInputError(
                "Backup contained no recognizable settings or API keys",
                status=400,
            )

        parts = []
        if cfg_keys_applied:
            parts.append(
                f"{cfg_keys_applied} setting{'s' if cfg_keys_applied != 1 else ''}"
            )
        if env_keys_applied:
            parts.append(
                f"{env_keys_applied} API key{'s' if env_keys_applied != 1 else ''}"
            )
        return json_success(message=f"Restored {' and '.join(parts)}")


@settings_bp.route("/settings/api-keys", methods=["GET"])
def api_keys_page() -> ResponseReturnValue:
    device_config = current_app.config["DEVICE_CONFIG"]

    def mask(value: str | None) -> str | None:
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
        active_nav="api-keys",
    )


@settings_bp.route("/settings/save_api_keys", methods=["POST"])
def save_api_keys() -> ResponseReturnValue:
    device_config = current_app.config["DEVICE_CONFIG"]
    with route_error_boundary(
        "saving API keys",
        logger=logger,
        hint="Ensure .env is writable and values are valid; check disk space and permissions.",
    ):
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
                logger.warning(
                    "Rejected save_api_keys value for %s: value is only U+2022 "
                    "placeholder characters (likely a stale cached page or a "
                    "client that appended to the legacy bullet pre-fill).",
                    key,
                )
                skipped_placeholder.append(key)
                continue
            device_config.set_env_key(key, value)
            updated.append(key)
        if skipped_placeholder:
            return json_success(
                message="API keys saved.",
                updated=updated,
                skipped_placeholder=skipped_placeholder,
            )
        return json_success(message="API keys saved.", updated=updated)


@settings_bp.route("/settings/delete_api_key", methods=["POST"])
def delete_api_key() -> ResponseReturnValue:
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
        raise ClientInputError("Invalid key name", status=400)
    with route_error_boundary(
        "deleting API key",
        logger=logger,
        hint="Verify .env file permissions and that the key exists.",
    ):
        device_config.unset_env_key(key)
        return json_success(message=f"Deleted {key}.")


def _field_error(message: str, field: str) -> JsonResponse:
    """Return a 422 validation error response for *field*."""
    return json_error(
        message,
        status=422,
        code="validation_error",
        details={"field": field},
    )


def _validate_interval(form_data: dict[str, str]) -> JsonResponse | None:
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


def _validate_device_name(
    form_data: dict[str, str],
) -> tuple[str | None, JsonResponse | None]:
    """Validate and normalize the submitted device name."""
    raw_device_name = form_data.get("deviceName", "")
    device_name = raw_device_name.strip()
    if not device_name:
        return None, _field_error("Device Name is required", "deviceName")
    if len(raw_device_name) > _DEVICE_NAME_MAX_LEN:
        return None, _field_error(
            f"Device Name must be {_DEVICE_NAME_MAX_LEN} characters or fewer",
            "deviceName",
        )
    if any(unicodedata.category(ch) == "Cc" and ch != "\t" for ch in raw_device_name):
        return None, _field_error(
            "Device Name may not contain control characters",
            "deviceName",
        )
    return device_name, None


def _validate_enum_field(
    form_data: dict[str, str],
    field: str,
    allowed: tuple[str, ...],
    *,
    required: bool = True,
) -> JsonResponse | None:
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


def _validate_image_settings(form_data: dict[str, str]) -> JsonResponse | None:
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


def _validate_settings_form(
    form_data: dict[str, str],
) -> tuple[JsonResponse | None, str | None]:
    """Validate settings form data and return any error plus normalized fields."""
    normalized_device_name, err = _validate_device_name(form_data)
    if err:
        return err, None

    err = _validate_interval(form_data)
    if err:
        return err, None

    # Timezone
    timezone_name = form_data.get("timezoneName")
    if not timezone_name:
        return _field_error("Time Zone is required", "timezoneName"), None
    if timezone_name not in available_timezones():
        return (
            _field_error(
                "Time Zone must be a valid IANA timezone (e.g. UTC, America/New_York)",
                "timezoneName",
            ),
            None,
        )

    time_format = form_data.get("timeFormat")
    if not time_format or time_format not in ("12h", "24h"):
        return _field_error("Time format is required", "timeFormat"), None

    err = _validate_enum_field(
        form_data, "orientation", ("horizontal", "vertical"), required=False
    )
    if err:
        return err, None
    err = _validate_enum_field(
        form_data, "previewSizeMode", ("native", "scaled", "fit"), required=False
    )
    if err:
        return err, None
    err = _validate_enum_field(
        form_data, SCREEN_RENDERING_KEY, SCREEN_RENDERING_MODES, required=False
    )
    if err:
        return err, None

    return _validate_image_settings(form_data), normalized_device_name


def _build_settings_dict(
    form_data: dict[str, str], normalized_device_name: str
) -> tuple[dict[str, Any], int]:
    """Build the persisted settings payload from validated form data."""
    unit = form_data.get("unit")
    interval = form_data.get("interval")
    assert interval is not None
    assert unit is not None
    plugin_cycle_interval_seconds = calculate_seconds(int(interval), unit)

    image_settings: dict[str, float | str] = {
        "saturation": float(form_data.get("saturation", "1.0")),
        "brightness": float(form_data.get("brightness", "1.0")),
        "sharpness": float(form_data.get("sharpness", "1.0")),
        "contrast": float(form_data.get("contrast", "1.0")),
    }
    settings: dict[str, Any] = {
        "name": normalized_device_name,
        "inverted_image": form_data.get("invertImage") == "on",
        "log_system_stats": form_data.get("logSystemStats") == "on",
        "timezone": form_data.get("timezoneName"),
        "time_format": form_data.get("timeFormat"),
        "plugin_cycle_interval_seconds": plugin_cycle_interval_seconds,
        "image_settings": image_settings,
        "preview_size_mode": form_data.get("previewSizeMode", "native"),
    }
    # Optional on the form: when it is left out, keep the saved value rather
    # than writing null, which the config schema rejects.
    if form_data.get("orientation"):
        settings["orientation"] = form_data["orientation"]
    if "inky_saturation" in form_data:
        image_settings["inky_saturation"] = float(
            form_data.get("inky_saturation", "0.5")
        )
    if SCREEN_RENDERING_KEY in form_data:
        image_settings[SCREEN_RENDERING_KEY] = form_data[SCREEN_RENDERING_KEY]
    return settings, plugin_cycle_interval_seconds


@settings_bp.route("/save_settings", methods=["POST"])
def save_settings() -> ResponseReturnValue:
    device_config = current_app.config["DEVICE_CONFIG"]

    with route_error_boundary(
        "saving device settings",
        logger=logger,
        hint="Check numeric values and config file permissions.",
    ):
        form_data = request.form.to_dict()

        error, normalized_device_name = _validate_settings_form(form_data)
        if error:
            return error
        assert normalized_device_name is not None

        previous_interval_seconds = device_config.get_config(
            "plugin_cycle_interval_seconds"
        )
        settings, plugin_cycle_interval_seconds = _build_settings_dict(
            form_data, normalized_device_name
        )
        device_config.update_config(settings)
        configure_log_timezone(settings.get("timezone"))

        if plugin_cycle_interval_seconds != previous_interval_seconds:
            # wake the background thread up to signal interval config change
            refresh_task = current_app.config["REFRESH_TASK"]
            refresh_task.signal_config_change()
    return json_success(message="Saved settings.")


# Legacy route aliases used by older UI/tests.
def device_settings_page() -> ResponseReturnValue:
    return settings_page()


def save_device_settings() -> ResponseReturnValue:
    return save_settings()


def display_settings_page() -> ResponseReturnValue:
    return settings_page()


def save_display_settings() -> ResponseReturnValue:
    return save_settings()


def network_settings_page() -> ResponseReturnValue:
    return settings_page()


def save_network_settings() -> ResponseReturnValue:
    return save_settings()


settings_bp.add_url_rule(
    "/settings/device", view_func=device_settings_page, methods=["GET"]
)
settings_bp.add_url_rule(
    "/settings/device", view_func=save_device_settings, methods=["POST"]
)
settings_bp.add_url_rule(
    "/settings/display", view_func=display_settings_page, methods=["GET"]
)
settings_bp.add_url_rule(
    "/settings/display", view_func=save_display_settings, methods=["POST"]
)
settings_bp.add_url_rule(
    "/settings/network", view_func=network_settings_page, methods=["GET"]
)
settings_bp.add_url_rule(
    "/settings/network", view_func=save_network_settings, methods=["POST"]
)
