"""Workflow services for plugin and playlist orchestration."""

from .playlist_workflows import (
    AddPluginWorkflowResult,
    WorkflowError as PlaylistWorkflowError,
    build_playlist_plugin_dict,
    normalize_instance_name,
    prepare_add_plugin_workflow,
    validate_plugin_refresh_settings,
)
from .plugin_workflows import (
    DEFAULT_PLAYLIST_NAME,
    DEFAULT_PLUGIN_INSTANCE_SUFFIX,
    DEFAULT_PLUGIN_REFRESH_INTERVAL_SECONDS,
    PluginSettingsWorkflowResult,
    WorkflowError as PluginWorkflowError,
    build_saved_settings_instance_name,
    ensure_playlist,
    save_plugin_settings_workflow,
)

__all__ = [
    "AddPluginWorkflowResult",
    "DEFAULT_PLAYLIST_NAME",
    "DEFAULT_PLUGIN_INSTANCE_SUFFIX",
    "DEFAULT_PLUGIN_REFRESH_INTERVAL_SECONDS",
    "PluginSettingsWorkflowResult",
    "PluginWorkflowError",
    "PlaylistWorkflowError",
    "build_playlist_plugin_dict",
    "build_saved_settings_instance_name",
    "ensure_playlist",
    "normalize_instance_name",
    "prepare_add_plugin_workflow",
    "save_plugin_settings_workflow",
    "validate_plugin_refresh_settings",
]
