# pyright: reportMissingImports=false
"""Unit tests for plugin workflow service helpers."""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any


@dataclass
class _PluginInstance:
    settings: dict[str, Any]


@dataclass
class _Playlist:
    name: str
    plugins: list[_PluginInstance] = field(default_factory=list)

    def find_plugin(self, plugin_id: str, instance_name: str):
        return next(
            (
                inst
                for inst in self.plugins
                if getattr(inst, "name", None) == instance_name
            ),
            None,
        )

    def add_plugin(self, plugin_data: dict[str, Any]) -> bool:
        inst = _PluginInstance(settings=dict(plugin_data.get("plugin_settings", {})))
        inst.name = plugin_data["name"]
        inst.plugin_id = plugin_data["plugin_id"]
        self.plugins.append(inst)
        return True


class _PlaylistManager:
    def __init__(self):
        self.playlists: list[_Playlist] = []

    def get_playlist(self, name: str):
        return next((pl for pl in self.playlists if pl.name == name), None)

    def add_playlist(self, name: str, start_time=None, end_time=None):
        self.playlists.append(_Playlist(name=name))
        return True

    def to_dict(self):
        return {
            "playlists": [
                {
                    "name": pl.name,
                    "plugins": [
                        {
                            "name": getattr(inst, "name", None),
                            "plugin_id": getattr(inst, "plugin_id", None),
                            "settings": dict(inst.settings),
                        }
                        for inst in pl.plugins
                    ],
                }
                for pl in self.playlists
            ]
        }


class _DeviceConfig:
    def __init__(self, plugin_config=None):
        self.plugin_config = plugin_config
        self.playlist_manager = _PlaylistManager()
        self.config_file = "/tmp/inkypi-device.json"
        self.updated_payloads: list[dict[str, Any]] = []

    def get_plugin(self, plugin_id: str):
        return self.plugin_config

    def update_atomic(self, update_fn):
        payload: dict[str, Any] = {}
        update_fn(payload)
        self.updated_payloads.append(payload)


class _Plugin:
    def __init__(self, validation_error: str | None = None):
        self.validation_error = validation_error

    def validate_settings(self, settings: dict[str, Any]):
        return self.validation_error


def _plugin_workflows_mod() -> ModuleType:
    return importlib.import_module("services.plugin_workflows")


def test_build_saved_settings_instance_name():
    plugin_workflows_mod = _plugin_workflows_mod()

    assert (
        plugin_workflows_mod.build_saved_settings_instance_name("weather")
        == "weather_saved_settings"
    )


def test_ensure_playlist_creates_default_playlist():
    plugin_workflows_mod = _plugin_workflows_mod()
    manager = _PlaylistManager()

    playlist, created = plugin_workflows_mod.ensure_playlist(
        manager, plugin_workflows_mod.DEFAULT_PLAYLIST_NAME
    )

    assert created is True
    assert playlist is not None
    assert playlist.name == plugin_workflows_mod.DEFAULT_PLAYLIST_NAME


def test_save_plugin_settings_workflow_creates_saved_settings_instance():
    plugin_workflows_mod = _plugin_workflows_mod()
    device_config = _DeviceConfig(plugin_config={"id": "weather"})
    manager = device_config.playlist_manager
    calls: list[tuple[str, str, dict[str, Any], dict[str, Any]]] = []

    def _record_change(config_dir, instance_name, before, after):
        calls.append((config_dir, instance_name, before, after))

    result = plugin_workflows_mod.save_plugin_settings_workflow(
        "weather",
        {"city": "London"},
        device_config,
        manager,
        get_plugin_instance_fn=lambda _cfg: _Plugin(),
        record_change_fn=_record_change,
    )

    assert isinstance(result, plugin_workflows_mod.PluginSettingsWorkflowResult)
    assert result.ok is True
    assert result.instance_name == "weather_saved_settings"
    assert result.playlist_name == plugin_workflows_mod.DEFAULT_PLAYLIST_NAME
    assert result.default_playlist_created is True
    assert result.before_settings == {}
    assert result.after_settings == {"city": "London"}
    assert len(calls) == 1
    assert calls[0][1] == "weather_saved_settings"
    assert manager.get_playlist(plugin_workflows_mod.DEFAULT_PLAYLIST_NAME) is not None
    assert manager.get_playlist(plugin_workflows_mod.DEFAULT_PLAYLIST_NAME).find_plugin(
        "weather", "weather_saved_settings"
    )


def test_save_plugin_settings_workflow_updates_existing_instance():
    plugin_workflows_mod = _plugin_workflows_mod()
    device_config = _DeviceConfig(plugin_config={"id": "weather"})
    manager = device_config.playlist_manager
    manager.add_playlist(plugin_workflows_mod.DEFAULT_PLAYLIST_NAME)
    playlist = manager.get_playlist(plugin_workflows_mod.DEFAULT_PLAYLIST_NAME)
    playlist.add_plugin(
        {
            "plugin_id": "weather",
            "name": "weather_saved_settings",
            "plugin_settings": {"city": "Paris", "units": "metric"},
            "refresh": {"interval": 3600},
        }
    )
    calls: list[tuple[str, str, dict[str, Any], dict[str, Any]]] = []

    result = plugin_workflows_mod.save_plugin_settings_workflow(
        "weather",
        {"city": "London"},
        device_config,
        manager,
        get_plugin_instance_fn=lambda _cfg: _Plugin(),
        record_change_fn=lambda *args: calls.append(args),
    )

    assert result.ok is True
    assert result.default_playlist_created is False
    assert result.before_settings == {"city": "Paris", "units": "metric"}
    assert result.after_settings == {"city": "London"}
    assert playlist.find_plugin("weather", "weather_saved_settings").settings == {
        "city": "London"
    }
    assert calls[0][2] == {"city": "Paris", "units": "metric"}


def test_save_plugin_settings_workflow_rejects_missing_plugin():
    plugin_workflows_mod = _plugin_workflows_mod()
    device_config = _DeviceConfig(plugin_config=None)
    result = plugin_workflows_mod.save_plugin_settings_workflow(
        "weather",
        {"city": "London"},
        device_config,
        device_config.playlist_manager,
    )

    assert result.ok is False
    assert result.error is not None
    assert result.error.status == 404
    assert result.error.message == "Plugin not found"


def test_save_plugin_settings_workflow_rejects_validation_error():
    plugin_workflows_mod = _plugin_workflows_mod()
    device_config = _DeviceConfig(plugin_config={"id": "weather"})
    result = plugin_workflows_mod.save_plugin_settings_workflow(
        "weather",
        {"city": "London"},
        device_config,
        device_config.playlist_manager,
        get_plugin_instance_fn=lambda _cfg: _Plugin("bad city"),
    )

    assert result.ok is False
    assert result.error is not None
    assert result.error.message == "bad city"
    assert result.error.status == 400
