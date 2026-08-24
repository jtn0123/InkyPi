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
    if plugin_id == "ai_image":
        provider = str(plugin_settings.get("provider") or "openai").strip().lower()
        required_key = {
            "openai": ("OpenAI", "OPEN_AI_SECRET"),
            "google": ("Google", "GOOGLE_AI_SECRET"),
        }.get(provider)
        if required_key is not None:
            service_name, env_key = required_key
            try:
                if device_config.load_env_key(env_key) is None:
                    return WorkflowError(
                        f"{service_name} AI API Key not configured.",
                        status=400,
                        field="provider",
                    )
            except Exception:
                logger.debug(
                    "Could not validate AI image provider key for %s",
                    sanitize_log_field(provider),
                    exc_info=True,
                )

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


def _validate_composite_regions(
    raw_regions: list[dict[str, Any]], device_config: Any
) -> tuple[list[dict[str, Any]] | None, WorkflowError | None]:
    """Structurally validate a composite screen's regions, shape, and bounds.

    Mirrors CompositeScreenRenderer.generate_image's own validation (shape +
    bounds + "is this plugin actually installed") so a bad region is
    rejected at save time rather than surfacing only on the next refresh.
    Unlike a real plugin's validate_settings(settings) — which never
    receives device_config, so BasePlugin subclasses can only check
    resolution-independent shape at save time — this workflow function does
    receive device_config, so it can check real canvas bounds too instead
    of waiting for the next refresh to reject an out-of-bounds region.
    """
    from plugins.base_plugin.base_plugin import BasePlugin
    from refresh_task.composite_render import CompositeScreenRenderer, parse_regions

    if not raw_regions:
        return None, WorkflowError(
            "At least one region must be configured", status=422, field="regionsJson"
        )
    try:
        regions = parse_regions(raw_regions)
    except RuntimeError as e:
        return None, WorkflowError(str(e), status=422, field="regionsJson")

    canvas_w, canvas_h = BasePlugin.get_oriented_dimensions(device_config)
    for region in regions:
        shape_error = CompositeScreenRenderer._validate_region(
            region, canvas_w, canvas_h
        )
        if shape_error:
            return None, WorkflowError(shape_error, status=422, field="regionsJson")
        try:
            plugin_config = device_config.get_plugin(region["plugin_id"])
        except Exception:
            logger.debug(
                "Could not look up plugin config for composite region %s",
                sanitize_log_field(region["plugin_id"]),
                exc_info=True,
            )
            plugin_config = None
        if not plugin_config:
            return None, WorkflowError(
                f"Plugin '{region['plugin_id']}' is not installed/registered.",
                status=422,
                field="regionsJson",
            )

    return regions, None


def prepare_add_composite_screen_workflow(
    raw_regions: list[dict[str, Any]],
    refresh_settings: dict[str, Any],
    *,
    playlist_manager: Any,
    device_config: Any,
) -> AddPluginWorkflowResult:
    """Validate and execute the add-composite-screen workflow.

    Parallel to prepare_add_plugin_workflow, reusing its playlist/instance-
    name/refresh-settings validation and add_plugin_to_playlist plumbing —
    a composite screen is a normal PluginInstance (model.COMPOSITE_PLUGIN_ID)
    whose settings["regions"] this function validates before saving.
    """
    from model import COMPOSITE_PLUGIN_ID

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

    existing = playlist_manager.find_plugin(COMPOSITE_PLUGIN_ID, instance_name)
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

    regions, regions_err = _validate_composite_regions(raw_regions, device_config)
    if regions_err:
        return _failure(
            regions_err.message,
            status=regions_err.status,
            field=regions_err.field,
        )

    assert instance_name is not None
    assert regions is not None
    plugin_dict = build_playlist_plugin_dict(
        COMPOSITE_PLUGIN_ID, {"regions": regions}, refresh_config or {}, instance_name
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
        logger.exception("Add-composite-screen workflow failed")
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


def prepare_update_composite_screen_workflow(
    instance_name: str,
    raw_regions: list[dict[str, Any]],
    *,
    playlist_manager: Any,
    device_config: Any,
) -> AddPluginWorkflowResult:
    """Validate and apply a region-list update to an existing composite screen.

    Only settings["regions"] changes here — refresh cadence is edited through
    the same generic "Edit refresh settings" modal every other plugin
    instance uses (PUT /update_plugin_instance/<name>), and a composite
    screen can't be moved between playlists any more than a real plugin
    instance can via that same route.
    """
    from model import COMPOSITE_PLUGIN_ID

    instance_name = (instance_name or "").strip()
    if not instance_name:
        return _failure("Instance name is required", status=422, field="instance_name")

    plugin_instance = playlist_manager.find_plugin(COMPOSITE_PLUGIN_ID, instance_name)
    if plugin_instance is None:
        return _failure(
            f"Composite screen '{instance_name}' was not found",
            status=404,
            code="not_found",
        )

    regions, regions_err = _validate_composite_regions(raw_regions, device_config)
    if regions_err:
        return _failure(
            regions_err.message,
            status=regions_err.status,
            field=regions_err.field,
        )
    assert regions is not None

    try:

        def _do_update(cfg: dict[str, Any]) -> None:
            plugin_instance.settings = {"regions": regions}

        device_config.update_atomic(_do_update)
    except Exception:
        logger.exception(
            "Update-composite-screen workflow failed for %s",
            sanitize_log_field(instance_name),
        )
        return _failure(
            _MSG_INVALID_PLAYLIST_REQUEST,
            status=500,
            code="internal_error",
        )

    return AddPluginWorkflowResult(
        ok=True,
        message="Composite screen updated.",
        instance_name=instance_name,
        plugin_dict={"regions": regions},
    )
