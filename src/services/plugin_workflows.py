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
from typing import TYPE_CHECKING, Protocol

from plugins.plugin_registry import get_plugin_instance
from services.workflow_errors import WorkflowError
from utils.form_utils import sanitize_log_field, validate_plugin_required_fields
from utils.json_types import JsonObject
from utils.plugin_history import record_change as _record_plugin_change

if TYPE_CHECKING:
    from config import Config
    from model import Playlist, PlaylistManager

logger = logging.getLogger(__name__)

DEFAULT_PLAYLIST_NAME = "Default"
DEFAULT_PLUGIN_INSTANCE_SUFFIX = "_saved_settings"
DEFAULT_PLUGIN_REFRESH_INTERVAL_SECONDS = 3600
DEFAULT_SUCCESS_MESSAGE = "Settings saved. Add to Playlist to schedule this instance."
DEFAULT_PLUGIN_NOT_FOUND_MESSAGE = "Plugin not found"
DEFAULT_PLUGIN_VALIDATION_MESSAGE = (
    "Settings validation failed. Please check your input."
)


class SettingsValidator(Protocol):
    """What saving needs from a plugin: its own check of the settings.

    ``BasePlugin`` is one. The required-field check reads more of the plugin
    (its settings schema), but looks for it rather than assuming it.
    """

    def validate_settings(self, settings: JsonObject) -> str | None: ...


@dataclass(slots=True)
class PluginSettingsWorkflowResult:
    """Result of saving plugin settings into the Default playlist."""

    ok: bool
    message: str
    instance_name: str | None = None
    playlist_name: str = DEFAULT_PLAYLIST_NAME
    default_playlist_created: bool = False
    plugin_loaded: bool = False
    before_settings: JsonObject = field(default_factory=dict)
    after_settings: JsonObject = field(default_factory=dict)
    error: WorkflowError | None = None
    warnings: list[str] = field(default_factory=list)


def build_saved_settings_instance_name(
    plugin_id: str,
    suffix: str = DEFAULT_PLUGIN_INSTANCE_SUFFIX,
) -> str:
    """Return the canonical saved-settings instance name for a plugin."""
    return f"{plugin_id}{suffix}"


def ensure_playlist(
    playlist_manager: PlaylistManager,
    playlist_name: str = DEFAULT_PLAYLIST_NAME,
    *,
    start_time: str | None = None,
    end_time: str | None = None,
) -> tuple[Playlist | None, bool]:
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
    details: JsonObject | None = None,
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
    device_config: Config, plugin_id: str, plugin_log_id: str
) -> JsonObject | PluginSettingsWorkflowResult:
    """Return the plugin's config, or the failure to report."""
    try:
        plugin_config = device_config.get_plugin(plugin_id)
    except Exception:
        logger.exception("Plugin lookup failed for %s", plugin_log_id)
        return _failure(
            DEFAULT_PLUGIN_NOT_FOUND_MESSAGE,
            status=500,
            code="internal_error",
        )

    if not plugin_config:
        return _failure(DEFAULT_PLUGIN_NOT_FOUND_MESSAGE, status=404)
    return plugin_config


def _load_plugin_for_validation(
    plugin_config: JsonObject,
    plugin_log_id: str,
    get_plugin_instance_fn: Callable[[JsonObject], SettingsValidator],
) -> SettingsValidator | None:
    try:
        return get_plugin_instance_fn(plugin_config)
    except Exception:
        logger.warning(
            "Could not load plugin instance for validation: %s", plugin_log_id
        )
        return None


def validate_plugin_for_save(
    plugin: SettingsValidator | None,
    plugin_settings: JsonObject,
    plugin_log_id: str,
    validate_required_fields_fn: Callable[
        [SettingsValidator, JsonObject], str | None
    ] = validate_plugin_required_fields,
) -> WorkflowError | None:
    """Distinguish invalid input from validators that cannot execute."""
    unavailable = WorkflowError(
        "Plugin validation is unavailable. Settings were not saved.",
        status=503,
        code="backend_unavailable",
    )
    if plugin is None:
        return unavailable
    try:
        required_error = validate_required_fields_fn(plugin, plugin_settings)
        if required_error:
            return WorkflowError(required_error)
        settings_error = plugin.validate_settings(plugin_settings)
        if settings_error:
            return WorkflowError(str(settings_error))
    except Exception:
        logger.warning(
            "Plugin validation unavailable for %s", plugin_log_id, exc_info=True
        )
        return unavailable
    return None


def _persist_plugin_settings(
    *,
    device_config: Config,
    playlist_manager: PlaylistManager,
    playlist_name: str,
    plugin_id: str,
    plugin_settings: JsonObject,
    instance_name: str,
    default_refresh_interval_seconds: int,
    plugin_log_id: str,
) -> tuple[JsonObject | None, bool, PluginSettingsWorkflowResult | None]:
    before_settings: JsonObject = {}
    created = False

    try:

        def _do_save_settings(cfg: JsonObject) -> None:
            nonlocal before_settings, created
            playlist, created = ensure_playlist(playlist_manager, playlist_name)
            if playlist is None:
                raise RuntimeError("Could not create saved settings playlist")
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
        return (
            None,
            False,
            _failure(
                "An internal error occurred",
                status=500,
                code="internal_error",
            ),
        )

    return before_settings, created, None


def record_saved_settings_change(
    *,
    device_config: Config,
    instance_name: str,
    before_settings: JsonObject,
    after_settings: JsonObject,
    plugin_log_id: str,
    record_change_fn: Callable[[str, str, JsonObject, JsonObject], bool | None] | None,
) -> str | None:
    if record_change_fn is None:
        return None

    try:
        config_dir = os.path.dirname(device_config.config_file)
        recorded = record_change_fn(
            config_dir, instance_name, before_settings, after_settings
        )
        if recorded is False:
            return "Settings saved, but change history could not be recorded."
    except Exception:
        logger.exception("Recording plugin history failed for %s", plugin_log_id)
        return "Settings saved, but change history could not be recorded."

    return None


def save_plugin_settings_workflow(
    plugin_id: str,
    plugin_settings: JsonObject,
    device_config: Config,
    playlist_manager: PlaylistManager,
    *,
    get_plugin_instance_fn: Callable[
        [JsonObject], SettingsValidator
    ] = get_plugin_instance,
    validate_required_fields_fn: Callable[
        [SettingsValidator, JsonObject], str | None
    ] = (validate_plugin_required_fields),
    record_change_fn: (
        Callable[[str, str, JsonObject, JsonObject], bool | None] | None
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
    plugin_config = _load_plugin_config(device_config, plugin_id, plugin_log_id)
    if isinstance(plugin_config, PluginSettingsWorkflowResult):
        return plugin_config

    plugin = _load_plugin_for_validation(
        plugin_config, plugin_log_id, get_plugin_instance_fn
    )
    validation_error = validate_plugin_for_save(
        plugin, plugin_settings, plugin_log_id, validate_required_fields_fn
    )
    if validation_error is not None:
        return _failure(
            validation_error.message,
            status=validation_error.status,
            code=validation_error.code,
            field=validation_error.field,
        )

    instance_name = build_saved_settings_instance_name(
        plugin_id, suffix=saved_instance_suffix
    )
    before_settings: JsonObject = {}
    after_settings = copy.deepcopy(plugin_settings)
    persisted_before_settings, created, persist_error = _persist_plugin_settings(
        device_config=device_config,
        playlist_manager=playlist_manager,
        playlist_name=default_playlist_name,
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

    history_warning = record_saved_settings_change(
        device_config=device_config,
        instance_name=instance_name,
        before_settings=before_settings,
        after_settings=after_settings,
        plugin_log_id=plugin_log_id,
        record_change_fn=record_change_fn,
    )

    return PluginSettingsWorkflowResult(
        ok=True,
        message=history_warning or DEFAULT_SUCCESS_MESSAGE,
        warnings=[history_warning] if history_warning else [],
        instance_name=instance_name,
        playlist_name=default_playlist_name,
        default_playlist_created=created,
        plugin_loaded=plugin is not None,
        before_settings=before_settings,
        after_settings=after_settings,
    )
