"""Service-layer workflows for saving plugin settings.

This module keeps the plugin-settings orchestration logic free of Flask so the
route handlers can become thin request/response adapters later.
"""

from __future__ import annotations

import copy
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from plugins.plugin_registry import get_plugin_instance
from utils.form_utils import sanitize_log_field, validate_plugin_required_fields
from utils.plugin_history import record_change as _record_plugin_change

logger = logging.getLogger(__name__)

DEFAULT_PLAYLIST_NAME = "Default"
DEFAULT_PLUGIN_INSTANCE_SUFFIX = "_saved_settings"
DEFAULT_PLUGIN_REFRESH_INTERVAL_SECONDS = 3600
DEFAULT_SUCCESS_MESSAGE = "Settings saved. Add to Playlist to schedule this instance."
DEFAULT_PLUGIN_NOT_FOUND_MESSAGE = "Plugin not found"
DEFAULT_PLUGIN_VALIDATION_MESSAGE = (
    "Settings validation failed. Please check your input."
)


@dataclass(frozen=True, slots=True)
class WorkflowError:
    """Structured error returned by service workflows."""

    message: str
    status: int = 400
    code: str = "validation_error"
    field: str | None = None
    details: dict[str, Any] | None = None

    def as_json_kwargs(self) -> dict[str, Any]:
        """Return keyword arguments compatible with ``utils.http_utils.json_error``."""
        payload: dict[str, Any] = {"status": self.status, "code": self.code}
        details: dict[str, Any] = dict(self.details or {})
        if self.field is not None:
            details.setdefault("field", self.field)
        if details:
            payload["details"] = details
        return payload


@dataclass(slots=True)
class PluginSettingsWorkflowResult:
    """Result of saving plugin settings into the Default playlist."""

    ok: bool
    message: str
    instance_name: str | None = None
    playlist_name: str = DEFAULT_PLAYLIST_NAME
    default_playlist_created: bool = False
    plugin_loaded: bool = False
    before_settings: dict[str, Any] = field(default_factory=dict)
    after_settings: dict[str, Any] = field(default_factory=dict)
    error: WorkflowError | None = None


def build_saved_settings_instance_name(
    plugin_id: str,
    suffix: str = DEFAULT_PLUGIN_INSTANCE_SUFFIX,
) -> str:
    """Return the canonical saved-settings instance name for a plugin."""
    return f"{plugin_id}{suffix}"


def ensure_playlist(
    playlist_manager: Any,
    playlist_name: str = DEFAULT_PLAYLIST_NAME,
    *,
    start_time: str | None = None,
    end_time: str | None = None,
) -> tuple[Any | None, bool]:
    """Return ``(playlist, created)`` while creating the playlist if needed."""
    playlist = playlist_manager.get_playlist(playlist_name)
    if playlist is not None:
        return playlist, False

    playlist_manager.add_playlist(playlist_name, start_time, end_time)
    playlist = playlist_manager.get_playlist(playlist_name)
    return playlist, playlist is not None


def _failure(
    message: str,
    *,
    status: int = 400,
    code: str = "validation_error",
    field: str | None = None,
    details: dict[str, Any] | None = None,
) -> PluginSettingsWorkflowResult:
    return PluginSettingsWorkflowResult(
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


def _load_plugin_config(
    device_config: Any, plugin_id: str, plugin_log_id: str
) -> tuple[Any | None, PluginSettingsWorkflowResult | None]:
    try:
        plugin_config = device_config.get_plugin(plugin_id)
    except Exception:
        logger.exception("Plugin lookup failed for %s", plugin_log_id)
        return None, _failure(
            DEFAULT_PLUGIN_NOT_FOUND_MESSAGE,
            status=500,
            code="internal_error",
        )

    if not plugin_config:
        return None, _failure(DEFAULT_PLUGIN_NOT_FOUND_MESSAGE, status=404)
    return plugin_config, None


def _load_plugin_for_validation(
    plugin_config: Any,
    plugin_log_id: str,
    get_plugin_instance_fn: Callable[[Any], Any],
) -> Any | None:
    try:
        return get_plugin_instance_fn(plugin_config)
    except Exception:
        logger.warning(
            "Could not load plugin instance for validation: %s", plugin_log_id
        )
        return None


def _validate_plugin_settings(
    plugin: Any | None,
    plugin_settings: dict[str, Any],
    plugin_log_id: str,
    validate_required_fields_fn: Callable[[Any, dict[str, Any]], str | None],
) -> PluginSettingsWorkflowResult | None:
    if plugin is None:
        return None

    try:
        validation_error = validate_required_fields_fn(plugin, plugin_settings)
        if validation_error:
            return _failure(validation_error, status=400)
    except Exception:
        logger.warning("Required-field validation failed for %s", plugin_log_id)

    try:
        settings_error = plugin.validate_settings(plugin_settings)
        if settings_error:
            return _failure(settings_error, status=400)
    except Exception:
        logger.warning(
            "Plugin validate_settings raised for %s",
            plugin_log_id,
            exc_info=True,
        )
        return _failure(DEFAULT_PLUGIN_VALIDATION_MESSAGE, status=400)

    return None


def _persist_plugin_settings(
    *,
    device_config: Any,
    playlist_manager: Any,
    playlist: Any,
    plugin_id: str,
    plugin_settings: dict[str, Any],
    instance_name: str,
    default_refresh_interval_seconds: int,
    plugin_log_id: str,
) -> tuple[dict[str, Any] | None, PluginSettingsWorkflowResult | None]:
    before_settings: dict[str, Any] = {}

    try:

        def _do_save_settings(cfg: dict[str, Any]) -> None:
            nonlocal before_settings
            inst = playlist.find_plugin(plugin_id, instance_name)
            if inst:
                before_settings = copy.deepcopy(inst.settings or {})
                inst.settings = copy.deepcopy(plugin_settings)
            else:
                added = playlist.add_plugin(
                    {
                        "plugin_id": plugin_id,
                        "refresh": {"interval": default_refresh_interval_seconds},
                        "plugin_settings": copy.deepcopy(plugin_settings),
                        "name": instance_name,
                    }
                )
                if not added:
                    raise RuntimeError(
                        f"Could not add saved settings instance '{instance_name}'"
                    )
            cfg["playlist_config"] = playlist_manager.to_dict()

        device_config.update_atomic(_do_save_settings)
    except Exception:
        logger.exception("Saving plugin settings failed for %s", plugin_log_id)
        return None, _failure(
            "An internal error occurred",
            status=500,
            code="internal_error",
        )

    return before_settings, None


def _record_saved_settings_change(
    *,
    device_config: Any,
    instance_name: str,
    before_settings: dict[str, Any],
    after_settings: dict[str, Any],
    plugin_log_id: str,
    record_change_fn: Callable[[str, str, dict[str, Any], dict[str, Any]], None] | None,
) -> PluginSettingsWorkflowResult | None:
    if record_change_fn is None:
        return None

    try:
        config_dir = os.path.dirname(device_config.config_file)
        record_change_fn(config_dir, instance_name, before_settings, after_settings)
    except Exception:
        logger.exception("Recording plugin history failed for %s", plugin_log_id)
        return _failure(
            "An internal error occurred",
            status=500,
            code="internal_error",
        )

    return None


def save_plugin_settings_workflow(
    plugin_id: str,
    plugin_settings: dict[str, Any],
    device_config: Any,
    playlist_manager: Any,
    *,
    get_plugin_instance_fn: Callable[[Any], Any] = get_plugin_instance,
    validate_required_fields_fn: Callable[[Any, dict[str, Any]], str | None] = (
        validate_plugin_required_fields
    ),
    record_change_fn: (
        Callable[[str, str, dict[str, Any], dict[str, Any]], None] | None
    ) = _record_plugin_change,
    default_playlist_name: str = DEFAULT_PLAYLIST_NAME,
    saved_instance_suffix: str = DEFAULT_PLUGIN_INSTANCE_SUFFIX,
    default_refresh_interval_seconds: int = DEFAULT_PLUGIN_REFRESH_INTERVAL_SECONDS,
) -> PluginSettingsWorkflowResult:
    """Persist plugin settings to the Default playlist.

    The workflow mirrors the route behavior but returns structured data instead
    of Flask responses.
    """
    plugin_log_id = sanitize_log_field(plugin_id)
    plugin_config, lookup_error = _load_plugin_config(
        device_config, plugin_id, plugin_log_id
    )
    if lookup_error is not None:
        return lookup_error

    plugin = _load_plugin_for_validation(
        plugin_config, plugin_log_id, get_plugin_instance_fn
    )
    validation_error = _validate_plugin_settings(
        plugin, plugin_settings, plugin_log_id, validate_required_fields_fn
    )
    if validation_error is not None:
        return validation_error

    playlist, created = ensure_playlist(playlist_manager, default_playlist_name)
    if playlist is None:
        return _failure(
            "Failed to create Default playlist",
            status=500,
            code="internal_error",
        )

    instance_name = build_saved_settings_instance_name(
        plugin_id, suffix=saved_instance_suffix
    )
    before_settings: dict[str, Any] = {}
    after_settings = copy.deepcopy(plugin_settings)
    persisted_before_settings, persist_error = _persist_plugin_settings(
        device_config=device_config,
        playlist_manager=playlist_manager,
        playlist=playlist,
        plugin_id=plugin_id,
        plugin_settings=plugin_settings,
        instance_name=instance_name,
        default_refresh_interval_seconds=default_refresh_interval_seconds,
        plugin_log_id=plugin_log_id,
    )
    if persist_error is not None:
        return persist_error
    if persisted_before_settings is not None:
        before_settings = persisted_before_settings

    record_error = _record_saved_settings_change(
        device_config=device_config,
        instance_name=instance_name,
        before_settings=before_settings,
        after_settings=after_settings,
        plugin_log_id=plugin_log_id,
        record_change_fn=record_change_fn,
    )
    if record_error is not None:
        return record_error

    return PluginSettingsWorkflowResult(
        ok=True,
        message=DEFAULT_SUCCESS_MESSAGE,
        instance_name=instance_name,
        playlist_name=default_playlist_name,
        default_playlist_created=created,
        plugin_loaded=plugin is not None,
        before_settings=before_settings,
        after_settings=after_settings,
    )
