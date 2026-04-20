"""Reusable request parsing and validation models for playlist/settings flows.

These helpers are intentionally Flask-free so route handlers can adopt them
incrementally without changing the surrounding response code all at once.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, SupportsFloat, SupportsIndex, SupportsInt, cast
from zoneinfo import available_timezones

from utils.messages import PLAYLIST_NAME_REQUIRED_ERROR
from utils.time_utils import calculate_seconds

_VALIDATION_CODE = "validation_error"
_PLAYLIST_NAME_MAX_LEN = 64
_PLAYLIST_NAME_RE = re.compile(r"^[A-Za-z0-9 _-]+$", re.ASCII)
_PLAYLIST_NAME_FORMAT_ERROR = (
    "Playlist name can only contain ASCII letters, "
    "numbers, spaces, underscores, and hyphens"
)
_TARGET_VERSION_RE = re.compile(r"^v?\d+\.\d+\.\d+(-[A-Za-z0-9.]+)?$", re.ASCII)
_DEVICE_NAME_MAX_LEN = 64
_CYCLE_MINUTES_MIN = 1
_CYCLE_MINUTES_MAX = 1440
_IMAGE_SETTING_MIN = 0.0
_IMAGE_SETTING_MAX = 10.0
_MSG_INVALID_TIME_FORMAT = "Invalid start/end time format"
_MSG_SAME_TIME = "Start time and End time cannot be the same"
_MSG_INVALID_REORDER_ENTRY = "ordered entries must include plugin_id and name"

TimeUnit = Literal["minute", "hour"]
TimeFormat = Literal["12h", "24h"]
Orientation = Literal["horizontal", "vertical"]
PreviewSizeMode = Literal["native", "scaled", "fit"]
ClientLogLevel = Literal["debug", "info", "warning", "error"]


class RequestValidationError(ValueError):
    """Structured validation error that route handlers can map to ``json_error``."""

    def __init__(
        self,
        message: str,
        *,
        status: int = 400,
        field: str | None = None,
        code: str | None = _VALIDATION_CODE,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.field = field
        self.code = code
        self._details = dict(details or {})

    @property
    def details(self) -> dict[str, object] | None:
        """Return structured error details suitable for ``json_error``."""
        details = dict(self._details)
        if self.field is not None and "field" not in details:
            details["field"] = self.field
        return details or None

    def as_json_error_kwargs(self) -> dict[str, Any]:
        """Return kwargs that can be passed directly to ``json_error``."""
        kwargs: dict[str, Any] = {
            "message": self.message,
            "status": self.status,
        }
        if self.code is not None:
            kwargs["code"] = self.code
        if self.details is not None:
            kwargs["details"] = self.details
        return kwargs


def require_mapping(
    payload: object,
    *,
    message: str = "Request body must be a JSON object",
    status: int = 400,
) -> Mapping[str, object]:
    """Ensure *payload* is a mapping and raise a structured error otherwise."""
    if not isinstance(payload, Mapping):
        raise RequestValidationError(message, status=status, code=None)
    return cast(Mapping[str, object], payload)


def _string_value(
    raw: object,
    *,
    field: str,
    status: int,
    required_message: str,
    invalid_message: str | None = None,
    strip: bool = True,
    max_length: int | None = None,
    max_length_message: str | None = None,
) -> str:
    if raw is None:
        raise RequestValidationError(required_message, status=status, field=field)
    if not isinstance(raw, str):
        raise RequestValidationError(
            invalid_message or f"{field} must be a string",
            status=status,
            field=field,
        )
    value = raw.strip() if strip else raw
    if not value:
        raise RequestValidationError(required_message, status=status, field=field)
    if max_length is not None and len(value) > max_length:
        raise RequestValidationError(
            max_length_message or f"{field} must be {max_length} characters or fewer",
            status=status,
            field=field,
        )
    return value


def _optional_string(raw: object, *, strip: bool = True) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        return None
    return raw.strip() if strip else raw


def _int_value(
    raw: object,
    *,
    field: str,
    status: int,
    required_message: str,
    invalid_message: str,
    min_value: int | None = None,
    max_value: int | None = None,
    range_message: str | None = None,
) -> int:
    if raw is None:
        raise RequestValidationError(required_message, status=status, field=field)
    if isinstance(raw, bool):
        raise RequestValidationError(invalid_message, status=status, field=field)
    if isinstance(raw, float):
        raise RequestValidationError(invalid_message, status=status, field=field)
    try:
        value = int(cast(str | bytes | bytearray | SupportsInt | SupportsIndex, raw))
    except (TypeError, ValueError) as exc:
        raise RequestValidationError(
            invalid_message, status=status, field=field
        ) from exc
    if min_value is not None and value < min_value:
        raise RequestValidationError(
            range_message or f"{field} must be at least {min_value}",
            status=status,
            field=field,
        )
    if max_value is not None and value > max_value:
        raise RequestValidationError(
            range_message or f"{field} must be at most {max_value}",
            status=status,
            field=field,
        )
    return value


def _float_value(
    raw: object,
    *,
    field: str,
    min_value: float,
    max_value: float,
) -> float:
    if raw is None:
        return 1.0
    if isinstance(raw, bool):
        raise RequestValidationError(
            f"Invalid numeric value for {field}",
            status=422,
            field=field,
        )
    try:
        value = float(
            cast(str | bytes | bytearray | SupportsFloat | SupportsIndex, raw)
        )
    except (TypeError, ValueError) as exc:
        raise RequestValidationError(
            f"Invalid numeric value for {field}",
            status=422,
            field=field,
        ) from exc
    if not math.isfinite(value):
        raise RequestValidationError(
            f"Invalid numeric value for {field}",
            status=422,
            field=field,
        )
    if value < min_value or value > max_value:
        raise RequestValidationError(
            f"{field} must be between {min_value} and {max_value}",
            status=422,
            field=field,
        )
    return value


def _bool_value(raw: object, *, default: bool = False) -> bool:
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        normalized = raw.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
        raise RequestValidationError(
            f"Invalid boolean value: {raw!r}",
            status=400,
        )
    raise RequestValidationError(
        f"Boolean value must be true/false or string, not {type(raw).__name__}",
        status=400,
    )


def _parse_time_field(raw: object, *, field: str) -> tuple[str, int]:
    value = _string_value(
        raw,
        field=field,
        status=400,
        required_message="Start time and End time are required",
        invalid_message=_MSG_INVALID_TIME_FORMAT,
    )
    try:
        minutes = _to_minutes(value)
    except Exception as exc:
        raise RequestValidationError(
            _MSG_INVALID_TIME_FORMAT,
            status=400,
            field=field,
        ) from exc
    return value, minutes


def _to_minutes(time_str: str) -> int:
    """Convert an ``HH:MM`` string to minutes since midnight."""
    if time_str == "24:00":
        return 24 * 60
    hour, minute = map(int, time_str.split(":"))
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError("Invalid time")
    return hour * 60 + minute


def _parse_playlist_name(raw: object, *, field: str) -> str:
    name = _string_value(
        raw,
        field=field,
        status=400,
        required_message=PLAYLIST_NAME_REQUIRED_ERROR,
        max_length=_PLAYLIST_NAME_MAX_LEN,
        max_length_message=(
            f"Playlist name must be {_PLAYLIST_NAME_MAX_LEN} characters or fewer"
        ),
    )
    if not _PLAYLIST_NAME_RE.match(name):
        raise RequestValidationError(
            _PLAYLIST_NAME_FORMAT_ERROR,
            status=400,
            field=field,
        )
    return name


def _parse_device_name(data: Mapping[str, object]) -> str:
    raw = _optional_string(data.get("deviceName"), strip=False) or ""
    device_name = raw.strip()
    if not device_name:
        raise RequestValidationError(
            "Device Name is required", status=422, field="deviceName"
        )
    if len(raw) > _DEVICE_NAME_MAX_LEN:
        raise RequestValidationError(
            f"Device Name must be {_DEVICE_NAME_MAX_LEN} characters or fewer",
            status=422,
            field="deviceName",
        )
    if any(unicodedata.category(ch) == "Cc" and ch != "\t" for ch in raw):
        raise RequestValidationError(
            "Device Name may not contain control characters",
            status=422,
            field="deviceName",
        )
    return device_name


def _parse_interval_seconds(data: Mapping[str, object]) -> tuple[int, TimeUnit]:
    unit_raw = data.get("unit")
    if unit_raw not in ("minute", "hour"):
        raise RequestValidationError(
            "Plugin cycle interval unit is required", status=422, field="unit"
        )
    unit: TimeUnit = unit_raw
    interval = _int_value(
        data.get("interval"),
        field="interval",
        status=422,
        required_message="Refresh interval is required",
        invalid_message="Refresh interval must be a number",
        min_value=1,
        range_message="Refresh interval must be at least 1",
    )
    interval_seconds = calculate_seconds(interval, unit)
    if interval_seconds >= 86400 or interval_seconds <= 0:
        raise RequestValidationError(
            "Plugin cycle interval must be less than 24 hours",
            status=422,
            field="interval",
        )
    return interval_seconds, unit


def _parse_enum(
    data: Mapping[str, object],
    *,
    field: str,
    allowed: Collection[str],
    required: bool,
    required_message: str,
) -> str | None:
    value = _optional_string(data.get(field))
    if value is None:
        if required:
            raise RequestValidationError(required_message, status=422, field=field)
        return None
    if value not in allowed:
        if required:
            raise RequestValidationError(required_message, status=422, field=field)
        allowed_str = ", ".join(repr(item) for item in allowed)
        raise RequestValidationError(
            f"{field} must be one of {allowed_str}", status=422, field=field
        )
    return value


@dataclass(frozen=True)
class PlaylistCreateRequest:
    """Validated payload for ``/create_playlist`` style requests."""

    playlist_name: str
    start_time: str
    end_time: str
    start_min: int
    end_min: int

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> PlaylistCreateRequest:
        playlist_name = _parse_playlist_name(
            data.get("playlist_name"), field="playlist_name"
        )
        start_time, start_min = _parse_time_field(
            data.get("start_time"), field="start_time"
        )
        end_time, end_min = _parse_time_field(data.get("end_time"), field="end_time")
        if start_min == end_min:
            raise RequestValidationError(_MSG_SAME_TIME, status=400, field="end_time")
        return cls(
            playlist_name=playlist_name,
            start_time=start_time,
            end_time=end_time,
            start_min=start_min,
            end_min=end_min,
        )


@dataclass(frozen=True)
class PlaylistUpdateRequest:
    """Validated payload for ``/update_playlist`` style requests."""

    new_name: str
    start_time: str
    end_time: str
    start_min: int
    end_min: int
    cycle_minutes: int | None = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> PlaylistUpdateRequest:
        new_name = _parse_playlist_name(data.get("new_name"), field="new_name")
        start_raw = data.get("start_time")
        end_raw = data.get("end_time")
        if not start_raw or not end_raw:
            missing_field = "start_time" if not start_raw else "end_time"
            raise RequestValidationError(
                "Missing required fields", status=400, field=missing_field
            )
        start_time, start_min = _parse_time_field(start_raw, field="start_time")
        end_time, end_min = _parse_time_field(end_raw, field="end_time")
        if start_min == end_min:
            raise RequestValidationError(_MSG_SAME_TIME, status=400, field="end_time")
        cycle_raw = data.get("cycle_minutes")
        cycle_minutes = None
        if cycle_raw is not None:
            cycle_minutes = _int_value(
                cycle_raw,
                field="cycle_minutes",
                status=400,
                required_message="cycle_minutes is required",
                invalid_message="cycle_minutes must be an integer",
                min_value=_CYCLE_MINUTES_MIN,
                max_value=_CYCLE_MINUTES_MAX,
                range_message=(
                    f"cycle_minutes must be between "
                    f"{_CYCLE_MINUTES_MIN} and {_CYCLE_MINUTES_MAX}"
                ),
            )
        return cls(
            new_name=new_name,
            start_time=start_time,
            end_time=end_time,
            start_min=start_min,
            end_min=end_min,
            cycle_minutes=cycle_minutes,
        )


@dataclass(frozen=True)
class PlaylistSelectionRequest:
    """Validated payload for actions that only need a playlist name."""

    playlist_name: str

    @classmethod
    def from_mapping(
        cls,
        data: Mapping[str, object],
        *,
        required_message: str = "playlist_name required",
        status: int = 400,
    ) -> PlaylistSelectionRequest:
        playlist_name = _string_value(
            data.get("playlist_name"),
            field="playlist_name",
            status=status,
            required_message=required_message,
        )
        return cls(playlist_name=playlist_name)


@dataclass(frozen=True)
class ReorderPluginItem:
    """One plugin entry in a reorder payload."""

    plugin_id: str
    name: str

    @classmethod
    def from_mapping(cls, payload: object) -> ReorderPluginItem:
        data = require_mapping(payload, message="ordered items must be JSON objects")
        plugin_id = _string_value(
            data.get("plugin_id"),
            field="ordered",
            status=400,
            required_message=_MSG_INVALID_REORDER_ENTRY,
            invalid_message=_MSG_INVALID_REORDER_ENTRY,
        )
        name = _string_value(
            data.get("name"),
            field="ordered",
            status=400,
            required_message=_MSG_INVALID_REORDER_ENTRY,
            invalid_message=_MSG_INVALID_REORDER_ENTRY,
        )
        return cls(plugin_id=plugin_id, name=name)

    def as_mapping(self) -> dict[str, str]:
        """Return the item in the shape expected by ``Playlist.reorder_plugins``."""
        return {"plugin_id": self.plugin_id, "name": self.name}


@dataclass(frozen=True)
class PlaylistReorderRequest:
    """Validated payload for ``/reorder_plugins``."""

    playlist_name: str
    ordered: tuple[ReorderPluginItem, ...] = field(default_factory=tuple)

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> PlaylistReorderRequest:
        playlist_name = _string_value(
            data.get("playlist_name"),
            field="playlist_name",
            status=400,
            required_message="playlist_name and ordered list are required",
        )
        ordered_raw = data.get("ordered")
        if not isinstance(ordered_raw, list):
            raise RequestValidationError(
                "playlist_name and ordered list are required",
                status=400,
                field="ordered",
            )
        ordered = tuple(ReorderPluginItem.from_mapping(item) for item in ordered_raw)
        return cls(playlist_name=playlist_name, ordered=ordered)

    def as_reorder_payload(self) -> list[dict[str, str]]:
        """Return the validated ordered list in the model-layer format."""
        return [item.as_mapping() for item in self.ordered]


@dataclass(frozen=True)
class DeviceCycleRequest:
    """Validated payload for ``/update_device_cycle``."""

    minutes: int

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> DeviceCycleRequest:
        minutes = _int_value(
            data.get("minutes"),
            field="minutes",
            status=400,
            required_message="Invalid minutes",
            invalid_message="Invalid minutes",
            min_value=_CYCLE_MINUTES_MIN,
            max_value=_CYCLE_MINUTES_MAX,
            range_message=(
                f"Minutes must be between {_CYCLE_MINUTES_MIN} and "
                f"{_CYCLE_MINUTES_MAX}"
            ),
        )
        return cls(minutes=minutes)


@dataclass(frozen=True)
class PluginIsolationRequest:
    """Validated payload for ``/settings/isolation``."""

    plugin_id: str

    @classmethod
    def from_mapping(
        cls,
        data: Mapping[str, object],
        *,
        registered_ids: Collection[str] | None = None,
    ) -> PluginIsolationRequest:
        plugin_id = _string_value(
            data.get("plugin_id"),
            field="plugin_id",
            status=422,
            required_message="plugin_id is required and must be a non-empty string",
            invalid_message="plugin_id is required and must be a non-empty string",
        )
        if registered_ids is not None and plugin_id not in registered_ids:
            raise RequestValidationError(
                "plugin_id must reference a registered plugin",
                status=422,
                field="plugin_id",
            )
        return cls(plugin_id=plugin_id)


@dataclass(frozen=True)
class ShutdownRequest:
    """Validated payload for ``/shutdown``."""

    reboot: bool = False

    @classmethod
    def from_optional_mapping(cls, payload: object | None) -> ShutdownRequest:
        if payload is None:
            return cls()
        data = require_mapping(payload)
        return cls(reboot=_bool_value(data.get("reboot"), default=False))


@dataclass(frozen=True)
class ClientLogRequest:
    """Validated payload for ``/settings/client_log``."""

    level: ClientLogLevel
    message: str
    extra: object | None = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> ClientLogRequest:
        raw_level = str(data.get("level") or "info").strip().lower()
        if raw_level == "debug":
            level: ClientLogLevel = "debug"
        elif raw_level in {"warn", "warning"}:
            level = "warning"
        elif raw_level in {"err", "error"}:
            level = "error"
        else:
            level = "info"
        message = str(data.get("message") or "")
        return cls(level=level, message=message, extra=data.get("extra"))


@dataclass(frozen=True)
class SettingsUpdateRequest:
    """Validated payload for ``/settings/update``."""

    target_version: str | None = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> SettingsUpdateRequest:
        if "target_version" not in data:
            return cls()
        raw = data.get("target_version")
        if raw is None or not isinstance(raw, str) or not raw.strip():
            raise RequestValidationError(
                "target_version must be a non-empty string",
                status=400,
                field="target_version",
            )
        target_version = raw.strip()
        if not _TARGET_VERSION_RE.fullmatch(target_version):
            raise RequestValidationError(
                "Invalid target version format",
                status=400,
                field="target_version",
            )
        return cls(target_version=target_version)


@dataclass(frozen=True)
class SettingsFormRequest:
    """Validated form payload for ``/save_settings``."""

    device_name: str
    timezone_name: str
    time_format: TimeFormat
    interval_seconds: int
    unit: TimeUnit
    orientation: Orientation | None
    preview_size_mode: PreviewSizeMode
    inverted_image: bool
    log_system_stats: bool
    saturation: float
    brightness: float
    sharpness: float
    contrast: float
    inky_saturation: float | None = None

    @classmethod
    def from_mapping(
        cls,
        data: Mapping[str, object],
        *,
        valid_timezones: Collection[str] | None = None,
    ) -> SettingsFormRequest:
        device_name = _parse_device_name(data)
        interval_seconds, unit = _parse_interval_seconds(data)

        timezone_name = _string_value(
            data.get("timezoneName"),
            field="timezoneName",
            status=422,
            required_message="Time Zone is required",
        )
        if valid_timezones is None:
            allowed_timezones = set(available_timezones())
        else:
            allowed_timezones = set(valid_timezones)
        if timezone_name not in allowed_timezones:
            raise RequestValidationError(
                "Time Zone must be a valid IANA timezone (e.g. UTC, America/New_York)",
                status=422,
                field="timezoneName",
            )

        time_format_raw = _parse_enum(
            data,
            field="timeFormat",
            allowed=("12h", "24h"),
            required=True,
            required_message="Time format is required",
        )
        time_format = cast(TimeFormat, time_format_raw)

        orientation_raw = _parse_enum(
            data,
            field="orientation",
            allowed=("horizontal", "vertical"),
            required=False,
            required_message="orientation is required",
        )
        orientation = cast(Orientation | None, orientation_raw)

        preview_raw = _parse_enum(
            data,
            field="previewSizeMode",
            allowed=("native", "scaled", "fit"),
            required=False,
            required_message="previewSizeMode is required",
        )
        preview_size_mode = cast(PreviewSizeMode, preview_raw or "native")

        inky_saturation_raw = data.get("inky_saturation")
        inky_saturation = None
        if inky_saturation_raw is not None:
            inky_saturation = _float_value(
                inky_saturation_raw,
                field="inky_saturation",
                min_value=_IMAGE_SETTING_MIN,
                max_value=_IMAGE_SETTING_MAX,
            )

        return cls(
            device_name=device_name,
            timezone_name=timezone_name,
            time_format=time_format,
            interval_seconds=interval_seconds,
            unit=unit,
            orientation=orientation,
            preview_size_mode=preview_size_mode,
            inverted_image=_bool_value(data.get("invertImage"), default=False),
            log_system_stats=_bool_value(data.get("logSystemStats"), default=False),
            saturation=_float_value(
                data.get("saturation"),
                field="saturation",
                min_value=_IMAGE_SETTING_MIN,
                max_value=_IMAGE_SETTING_MAX,
            ),
            brightness=_float_value(
                data.get("brightness"),
                field="brightness",
                min_value=_IMAGE_SETTING_MIN,
                max_value=_IMAGE_SETTING_MAX,
            ),
            sharpness=_float_value(
                data.get("sharpness"),
                field="sharpness",
                min_value=_IMAGE_SETTING_MIN,
                max_value=_IMAGE_SETTING_MAX,
            ),
            contrast=_float_value(
                data.get("contrast"),
                field="contrast",
                min_value=_IMAGE_SETTING_MIN,
                max_value=_IMAGE_SETTING_MAX,
            ),
            inky_saturation=inky_saturation,
        )

    def to_settings_dict(self) -> dict[str, object]:
        """Return the persisted device settings structure used by the routes."""
        image_settings: dict[str, float] = {
            "saturation": self.saturation,
            "brightness": self.brightness,
            "sharpness": self.sharpness,
            "contrast": self.contrast,
        }
        if self.inky_saturation is not None:
            image_settings["inky_saturation"] = self.inky_saturation
        return {
            "name": self.device_name,
            "orientation": self.orientation,
            "inverted_image": self.inverted_image,
            "log_system_stats": self.log_system_stats,
            "timezone": self.timezone_name,
            "time_format": self.time_format,
            "plugin_cycle_interval_seconds": self.interval_seconds,
            "image_settings": image_settings,
            "preview_size_mode": self.preview_size_mode,
        }


@dataclass(frozen=True)
class SettingsImportRequest:
    """Validated payload for ``/settings/import``."""

    config: dict[str, object]
    env_keys: dict[str, str]

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, object],
        *,
        allowed_config_keys: Collection[str],
        allowed_env_keys: Collection[str],
    ) -> SettingsImportRequest:
        config_raw = payload.get("config", {})
        env_keys_raw = payload.get("env_keys", {})
        if not isinstance(config_raw, Mapping):
            raise RequestValidationError(
                "config must be a JSON object", status=400, field="config"
            )
        if not isinstance(env_keys_raw, Mapping):
            raise RequestValidationError(
                "env_keys must be a JSON object", status=400, field="env_keys"
            )
        config = {
            str(key): value
            for key, value in config_raw.items()
            if str(key) in set(allowed_config_keys)
        }
        env_keys = {
            str(key): str(value)
            for key, value in env_keys_raw.items()
            if str(key) in set(allowed_env_keys) and value is not None
        }
        return cls(config=config, env_keys=env_keys)


__all__ = [
    "ClientLogRequest",
    "ClientLogLevel",
    "DeviceCycleRequest",
    "PlaylistCreateRequest",
    "PlaylistReorderRequest",
    "PlaylistSelectionRequest",
    "PlaylistUpdateRequest",
    "PluginIsolationRequest",
    "ReorderPluginItem",
    "RequestValidationError",
    "SettingsFormRequest",
    "SettingsImportRequest",
    "SettingsUpdateRequest",
    "ShutdownRequest",
    "require_mapping",
]