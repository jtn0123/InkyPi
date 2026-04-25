"""Service-layer workflows for adding plugin instances to playlists."""

from __future__ import annotations

import copy
import logging
import re
import time as _time
from dataclasses import dataclass, field
from typing import Any, cast

from utils.form_utils import sanitize_log_field
from utils.messages import PLAYLIST_NAME_REQUIRED_ERROR
from utils.time_utils import calculate_seconds

logger = logging.getLogger(__name__)

_CODE_VALIDATION = "validation_error"
_INSTANCE_NAME_RE = re.compile(r"^[A-Za-z0-9 _-]+$")
_MAX_INSTANCE_NAME_LEN = 64
_MAX_REFRESH_INTERVAL = 999
_MSG_INVALID_PLAYLIST_REQUEST = "Invalid playlist request"


@dataclass(frozen=True, slots=True)
class WorkflowError:
    """Structured error returned by service workflows."""

    message: str
    status: int = 400
    code: str = _CODE_VALIDATION
    field: str | None = None
    details: dict[str, Any] | None = None

    def as_json_kwargs(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": self.status, "code": self.code}
        details: dict[str, Any] = dict(self.details or {})
        if self.field is not None:
            details.setdefault("field", self.field)
        if details:
            payload["details"] = details
        return payload


@dataclass(slots=True)
class AddPluginWorkflowResult:
    """Result of preparing and applying an add-plugin request."""

    ok: bool
    message: str
    playlist_name: str | None = None
    instance_name: str | None = None
    refresh_config: dict[str, Any] = field(default_factory=dict)
    plugin_dict: dict[str, Any] = field(default_factory=dict)
    error: WorkflowError | None = None


def _failure(
    message: str,
    *,
    status: int = 400,
    code: str = _CODE_VALIDATION,
    field: str | None = None,
    details: dict[str, Any] | None = None,
) -> AddPluginWorkflowResult:
    return AddPluginWorkflowResult(
        ok=False,
        message=message,
        error=WorkflowError(
            message=message,
            status=status,
            code=code,
            field=field,
            details=details,
        ),
    )


def normalize_instance_name(raw_name: Any) -> tuple[str | None, WorkflowError | None]:
    """Trim and validate a playlist instance name."""
    name = raw_name.strip() if isinstance(raw_name, str) else ""
    if not name:
        return None, WorkflowError(
            "Instance name is required",
            status=422,
            field="instance_name",
        )
    if len(name) > _MAX_INSTANCE_NAME_LEN:
        return None, WorkflowError(
            "Instance name must be 64 characters or fewer",
            status=422,
            field="instance_name",
        )
    if not _INSTANCE_NAME_RE.match(name):
        return None, WorkflowError(
            "Instance name can only contain letters, numbers, spaces, underscores, and hyphens",
            status=422,
            field="instance_name",
        )
    return name, None


def _validate_interval_refresh_settings(
    refresh_settings: dict[str, Any],
) -> tuple[dict[str, Any] | None, WorkflowError | None]:
    unit = refresh_settings.get("unit")
    interval = refresh_settings.get("interval")
    if not unit or unit not in {"minute", "hour", "day"}:
        return None, WorkflowError(
            "Refresh interval unit is required",
            status=422,
            field="unit",
        )
    if not interval:
        return None, WorkflowError(
            "Refresh interval is required",
            status=422,
            field="interval",
        )
    try:
        interval_int = int(interval)
    except (TypeError, ValueError):
        return None, WorkflowError(
            "Refresh interval must be a number",
            status=422,
            field="interval",
        )
    if interval_int < 1 or interval_int > _MAX_REFRESH_INTERVAL:
        return None, WorkflowError(
            "Refresh interval must be between 1 and 999",
            status=422,
            field="interval",
        )
    return {"interval": calculate_seconds(interval_int, unit)}, None


def _validate_scheduled_refresh_settings(
    refresh_settings: dict[str, Any],
) -> tuple[dict[str, Any] | None, WorkflowError | None]:
    refresh_time = refresh_settings.get("refreshTime")
    if not refresh_time:
        return None, WorkflowError(
            "Refresh time is required",
            status=422,
            field="refreshTime",
        )
    if not isinstance(refresh_time, str):
        return None, WorkflowError(
            "Refresh time must be in HH:MM format",
            status=422,
            field="refreshTime",
        )
    refresh_time = refresh_time.strip()
    try:
        _time.strptime(refresh_time, "%H:%M")
    except ValueError:
        return None, WorkflowError(
            "Refresh time must be in HH:MM format",
            status=422,
            field="refreshTime",
        )
    return {"scheduled": refresh_time}, None


def validate_plugin_refresh_settings(
    refresh_settings: dict[str, Any],
) -> tuple[dict[str, Any] | None, WorkflowError | None]:
    """Validate the refresh settings from ``/add_plugin``."""
    refresh_type = refresh_settings.get("refreshType")
    if not refresh_type or refresh_type not in {"interval", "scheduled"}:
        return None, WorkflowError(
            "Refresh type is required",
            status=422,
            field="refreshType",
        )
    if refresh_type == "interval":
        return _validate_interval_refresh_settings(refresh_settings)
    return _validate_scheduled_refresh_settings(refresh_settings)


def validate_plugin_settings_security(
    device_config: Any, plugin_id: str, plugin_settings: dict[str, Any]
) -> WorkflowError | None:
    """Run plugin-specific validation for settings that are about to be added."""
    if not plugin_settings:
        return None
    plugin_config = None
    try:
        plugin_config = device_config.get_plugin(plugin_id)
    except Exception:
        logger.debug(
            "Could not load plugin config for security validation", exc_info=True
        )
        return None
    if not plugin_config:
        return None

    try:
        from plugins.plugin_registry import get_plugin_instance as _get_plugin_instance

        plugin_obj = cast(Any, _get_plugin_instance)(plugin_config)
        settings_error = plugin_obj.validate_settings(plugin_settings)
        if settings_error:
            return WorkflowError(str(settings_error), status=400)
    except Exception:
        logger.debug(
            "Could not validate plugin schema for %s",
            sanitize_log_field(plugin_id),
            exc_info=True,
        )
    return None


def build_playlist_plugin_dict(
    plugin_id: str,
    plugin_settings: dict[str, Any],
    refresh_config: dict[str, Any],
    instance_name: str,
) -> dict[str, Any]:
    """Build the dict passed to ``PlaylistManager.add_plugin_to_playlist``."""
    return {
        "plugin_id": plugin_id,
        "refresh": copy.deepcopy(refresh_config),
        "plugin_settings": copy.deepcopy(plugin_settings),
        "name": instance_name,
    }


def prepare_add_plugin_workflow(
    plugin_id: str,
    plugin_settings: dict[str, Any],
    refresh_settings: dict[str, Any],
    *,
    playlist_manager: Any,
    device_config: Any,
) -> AddPluginWorkflowResult:
    """Validate and execute the add-plugin workflow used by ``/add_plugin``."""
    playlist = refresh_settings.get("playlist")
    if not playlist:
        return _failure(
            PLAYLIST_NAME_REQUIRED_ERROR,
            status=422,
            field="playlist",
        )

    instance_name, name_err = normalize_instance_name(
        refresh_settings.get("instance_name")
    )
    if name_err:
        return _failure(
            name_err.message,
            status=name_err.status,
            code=name_err.code,
            field=name_err.field,
        )

    existing = playlist_manager.find_plugin(plugin_id, instance_name)
    if existing:
        return _failure(
            f"Plugin instance '{instance_name}' already exists",
            status=400,
            field="instance_name",
        )

    refresh_config, refresh_err = validate_plugin_refresh_settings(refresh_settings)
    if refresh_err:
        return _failure(
            refresh_err.message,
            status=refresh_err.status,
            field=refresh_err.field,
        )

    security_err = validate_plugin_settings_security(
        device_config, plugin_id, plugin_settings
    )
    if security_err:
        return _failure(
            security_err.message,
            status=security_err.status,
            field=security_err.field,
        )

    assert instance_name is not None
    plugin_dict = build_playlist_plugin_dict(
        plugin_id, plugin_settings, refresh_config or {}, instance_name
    )

    try:
        add_result: list[bool] = []

        def _do_add(cfg: dict[str, Any]) -> None:
            add_result.append(
                playlist_manager.add_plugin_to_playlist(playlist, plugin_dict)
            )
            cfg["playlist_config"] = playlist_manager.to_dict()

        device_config.update_atomic(_do_add)
        if not add_result or not add_result[0]:
            return _failure("Failed to add to playlist", status=500)
    except Exception:
        logger.exception("Add-plugin workflow failed for %s", plugin_id)
        return _failure(
            _MSG_INVALID_PLAYLIST_REQUEST,
            status=500,
            code="internal_error",
        )

    return AddPluginWorkflowResult(
        ok=True,
        message="Scheduled refresh configured.",
        playlist_name=playlist,
        instance_name=instance_name,
        refresh_config=refresh_config or {},
        plugin_dict=plugin_dict,
    )
