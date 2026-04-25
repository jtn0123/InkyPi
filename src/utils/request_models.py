"""Typed request models for high-churn mutating routes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from model import Playlist
from utils.messages import PLAYLIST_NAME_REQUIRED_ERROR

CODE_VALIDATION = "validation_error"
PLAYLIST_NAME_MAX_LEN = 64
PLAYLIST_NAME_RE = re.compile(r"^[A-Za-z0-9 _-]+$", re.ASCII)
PLAYLIST_NAME_FORMAT_ERROR = (
    "Playlist name can only contain ASCII letters, "
    "numbers, spaces, underscores, and hyphens"
)
INVALID_TIME_FORMAT_MESSAGE = "Invalid start/end time format"
SAME_TIME_MESSAGE = "Start time and End time cannot be the same"
CYCLE_MINUTES_MIN = 1
CYCLE_MINUTES_MAX = 1440


@dataclass(frozen=True, slots=True)
class RequestModelError:
    """Structured validation error for request model parsing."""

    message: str
    status: int = 400
    code: str = CODE_VALIDATION
    field: str | None = None

    @property
    def details(self) -> dict[str, str]:
        if self.field is None:
            return {}
        return {"field": self.field}


@dataclass(frozen=True, slots=True)
class PlaylistCreateRequest:
    """Validated payload for creating a playlist."""

    playlist_name: str
    start_time: str
    end_time: str
    start_min: int
    end_min: int


@dataclass(frozen=True, slots=True)
class PlaylistUpdateRequest:
    """Validated payload for updating a playlist."""

    new_name: str
    start_time: str
    end_time: str
    start_min: int
    end_min: int
    cycle_minutes_int: int | None


@dataclass(frozen=True, slots=True)
class ApiKeysSaveRequest:
    """Validated payload for saving API key entries."""

    entries: list[Any]


@dataclass(frozen=True, slots=True)
class PluginOrderRequest:
    """Validated dashboard plugin order payload."""

    order: list[str]


@dataclass(frozen=True, slots=True)
class DeviceCycleRequest:
    """Validated device refresh cadence payload."""

    minutes: int


@dataclass(frozen=True, slots=True)
class PlaylistPluginOrderItem:
    """A plugin instance position in a playlist reorder request."""

    plugin_id: str
    name: str

    def as_payload(self) -> dict[str, str]:
        return {"plugin_id": self.plugin_id, "name": self.name}


@dataclass(frozen=True, slots=True)
class PlaylistReorderRequest:
    """Validated payload for playlist plugin reordering."""

    playlist_name: str
    ordered: list[PlaylistPluginOrderItem]

    def ordered_payload(self) -> list[dict[str, str]]:
        return [item.as_payload() for item in self.ordered]


@dataclass(frozen=True, slots=True)
class PlaylistNameRequest:
    """Validated payload for playlist actions that only need a name."""

    playlist_name: str


@dataclass(frozen=True, slots=True)
class PluginInstanceActionRequest:
    """Validated payload for actions against one plugin instance."""

    playlist_name: str
    plugin_id: str | None
    plugin_instance: str | None


def validate_playlist_name(
    name: Any, *, field: str = "playlist_name"
) -> tuple[str | None, RequestModelError | None]:
    """Validate a playlist name and return its stripped value."""
    if not isinstance(name, str) or not name.strip():
        return None, RequestModelError(PLAYLIST_NAME_REQUIRED_ERROR, field=field)

    normalized = name.strip()
    if len(normalized) > PLAYLIST_NAME_MAX_LEN:
        return None, RequestModelError(
            f"Playlist name must be {PLAYLIST_NAME_MAX_LEN} characters or fewer",
            field=field,
        )
    if not PLAYLIST_NAME_RE.match(normalized):
        return None, RequestModelError(PLAYLIST_NAME_FORMAT_ERROR, field=field)
    return normalized, None


def _to_minutes(time_str: str) -> int:
    return int(Playlist._to_minutes(time_str))


def validate_playlist_times(
    start_time: Any, end_time: Any
) -> tuple[int | None, int | None, RequestModelError | None]:
    """Validate start/end playlist times and return minute offsets."""
    if not start_time:
        missing_field = "start_time"
    elif not end_time:
        missing_field = "end_time"
    else:
        missing_field = None

    if missing_field is not None:
        return (
            None,
            None,
            RequestModelError(
                "Start time and End time are required",
                field=missing_field,
            ),
        )

    try:
        start_min = _to_minutes(str(start_time))
    except Exception:
        return (
            None,
            None,
            RequestModelError(
                INVALID_TIME_FORMAT_MESSAGE,
                field="start_time",
            ),
        )
    try:
        end_min = _to_minutes(str(end_time))
    except Exception:
        return (
            None,
            None,
            RequestModelError(
                INVALID_TIME_FORMAT_MESSAGE,
                field="end_time",
            ),
        )
    if start_min == end_min:
        return None, None, RequestModelError(SAME_TIME_MESSAGE, field="end_time")
    return start_min, end_min, None


def validate_cycle_minutes(
    cycle_minutes: Any,
) -> tuple[int | None, RequestModelError | None]:
    """Validate an optional playlist cycle override in minutes."""
    if cycle_minutes is None:
        return None, None
    try:
        cycle_minutes_int = int(cycle_minutes)
    except (ValueError, TypeError):
        return None, RequestModelError(
            "cycle_minutes must be an integer",
            field="cycle_minutes",
        )
    if cycle_minutes_int < CYCLE_MINUTES_MIN or cycle_minutes_int > CYCLE_MINUTES_MAX:
        return None, RequestModelError(
            f"cycle_minutes must be between {CYCLE_MINUTES_MIN} and {CYCLE_MINUTES_MAX}",
            field="cycle_minutes",
        )
    return cycle_minutes_int, None


def parse_api_keys_save_request(
    data: Any,
) -> tuple[ApiKeysSaveRequest | None, RequestModelError | None]:
    """Parse and validate the API-key save payload envelope."""
    if not isinstance(data, dict):
        return None, RequestModelError("Invalid JSON payload")
    entries = data.get("entries", [])
    if not isinstance(entries, list):
        return None, RequestModelError("Invalid entries format", field="entries")
    return ApiKeysSaveRequest(entries=entries), None


def parse_plugin_order_request(
    data: Any,
) -> tuple[PluginOrderRequest | None, RequestModelError | None]:
    """Parse and validate the dashboard plugin order payload envelope."""
    if not isinstance(data, dict):
        return None, RequestModelError("Invalid JSON payload")
    order = data.get("order", [])
    if not isinstance(order, list):
        return None, RequestModelError("Order must be a list", field="order")
    if any(not isinstance(item, str) for item in order):
        return None, RequestModelError("Order entries must be strings", field="order")
    return PluginOrderRequest(order=order), None


def parse_device_cycle_request(
    data: Any,
) -> tuple[DeviceCycleRequest | None, RequestModelError | None]:
    """Parse and validate a device refresh cadence payload."""
    if not isinstance(data, dict):
        return None, RequestModelError("Invalid minutes", field="minutes")
    minutes = data.get("minutes") or 0
    try:
        minutes_int = int(minutes)
    except (ValueError, TypeError):
        return None, RequestModelError("Invalid minutes", field="minutes")
    if minutes_int < CYCLE_MINUTES_MIN or minutes_int > CYCLE_MINUTES_MAX:
        return None, RequestModelError(
            f"Minutes must be between {CYCLE_MINUTES_MIN} and {CYCLE_MINUTES_MAX}",
            field="minutes",
        )
    return DeviceCycleRequest(minutes=minutes_int), None


def parse_playlist_create_request(
    data: dict[str, Any],
) -> tuple[PlaylistCreateRequest | None, RequestModelError | None]:
    """Parse and validate a create-playlist payload."""
    playlist_name, name_err = validate_playlist_name(data.get("playlist_name"))
    if name_err is not None or playlist_name is None:
        return None, name_err

    start_time = data.get("start_time")
    end_time = data.get("end_time")
    start_min, end_min, time_err = validate_playlist_times(start_time, end_time)
    if time_err is not None or start_min is None or end_min is None:
        return None, time_err

    return (
        PlaylistCreateRequest(
            playlist_name=playlist_name,
            start_time=str(start_time),
            end_time=str(end_time),
            start_min=start_min,
            end_min=end_min,
        ),
        None,
    )


def parse_playlist_update_request(
    data: dict[str, Any],
) -> tuple[PlaylistUpdateRequest | None, RequestModelError | None]:
    """Parse and validate an update-playlist payload."""
    new_name, name_err = validate_playlist_name(data.get("new_name"), field="new_name")
    if name_err is not None or new_name is None:
        return None, name_err

    start_time = data.get("start_time")
    end_time = data.get("end_time")
    if not start_time or not end_time:
        missing_field = "start_time" if not start_time else "end_time"
        return None, RequestModelError("Missing required fields", field=missing_field)

    start_min, end_min, time_err = validate_playlist_times(start_time, end_time)
    if time_err is not None or start_min is None or end_min is None:
        return None, time_err

    cycle_minutes_int, cycle_err = validate_cycle_minutes(data.get("cycle_minutes"))
    if cycle_err is not None:
        return None, cycle_err

    return (
        PlaylistUpdateRequest(
            new_name=new_name,
            start_time=str(start_time),
            end_time=str(end_time),
            start_min=start_min,
            end_min=end_min,
            cycle_minutes_int=cycle_minutes_int,
        ),
        None,
    )


def parse_playlist_reorder_request(
    data: Any,
) -> tuple[PlaylistReorderRequest | None, RequestModelError | None]:
    """Parse and validate a playlist plugin reorder payload."""
    if not isinstance(data, dict):
        return None, RequestModelError("Invalid or missing JSON payload")

    playlist_name = data.get("playlist_name")
    if not isinstance(playlist_name, str) or not playlist_name.strip():
        return None, RequestModelError(
            "playlist_name and ordered list are required",
            field="playlist_name",
        )

    ordered = data.get("ordered")
    if not isinstance(ordered, list):
        return None, RequestModelError(
            "playlist_name and ordered list are required",
            field="ordered",
        )

    parsed_ordered: list[PlaylistPluginOrderItem] = []
    for item in ordered:
        if not isinstance(item, dict):
            return None, RequestModelError("Invalid order payload", field="ordered")
        plugin_id = item.get("plugin_id")
        name = item.get("name")
        if not isinstance(plugin_id, str) or not isinstance(name, str):
            return None, RequestModelError("Invalid order payload", field="ordered")
        parsed_ordered.append(PlaylistPluginOrderItem(plugin_id=plugin_id, name=name))

    return (
        PlaylistReorderRequest(
            playlist_name=playlist_name.strip(),
            ordered=parsed_ordered,
        ),
        None,
    )


def parse_playlist_name_request(
    data: Any, *, missing_message: str
) -> tuple[PlaylistNameRequest | None, RequestModelError | None]:
    """Parse and validate a playlist action payload containing only a name."""
    if not isinstance(data, dict):
        return None, RequestModelError("Invalid or missing JSON payload")
    playlist_name = data.get("playlist_name")
    if not isinstance(playlist_name, str) or not playlist_name.strip():
        return None, RequestModelError(missing_message, field="playlist_name")
    return PlaylistNameRequest(playlist_name=playlist_name.strip()), None


def parse_plugin_instance_action_request(
    data: Any,
    *,
    missing_playlist_message: str = PLAYLIST_NAME_REQUIRED_ERROR,
) -> tuple[PluginInstanceActionRequest | None, RequestModelError | None]:
    """Parse and validate a plugin-instance action payload.

    ``plugin_id`` and ``plugin_instance`` stay optional here because existing
    routes report missing or unknown instances through their lookup path. The
    model still centralizes JSON/object and playlist-name validation.
    """
    if not isinstance(data, dict):
        return None, RequestModelError("Invalid or missing JSON payload")

    playlist_name = data.get("playlist_name")
    if not isinstance(playlist_name, str) or not playlist_name.strip():
        return None, RequestModelError(
            missing_playlist_message,
            field="playlist_name",
        )

    plugin_id = data.get("plugin_id")
    plugin_instance = data.get("plugin_instance")
    return (
        PluginInstanceActionRequest(
            playlist_name=playlist_name.strip(),
            plugin_id=plugin_id if isinstance(plugin_id, str) else None,
            plugin_instance=(
                plugin_instance if isinstance(plugin_instance, str) else None
            ),
        ),
        None,
    )
