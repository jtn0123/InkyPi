# pyright: reportMissingImports=false
"""Unit tests for playlist workflow service helpers."""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any


@dataclass
class _PluginInstance:
    plugin_id: str
    name: str
    settings: dict[str, Any]
    refresh: dict[str, Any]


@dataclass
class _Playlist:
    name: str
    plugins: list[_PluginInstance] = field(default_factory=list)

    def find_plugin(self, plugin_id: str, instance_name: str):
        return next(
            (
                inst
                for inst in self.plugins
                if inst.plugin_id == plugin_id and inst.name == instance_name
            ),
            None,
        )

    def add_plugin(self, plugin_data: dict[str, Any]) -> bool:
        if self.find_plugin(plugin_data["plugin_id"], plugin_data["name"]):
            return False
        self.plugins.append(
            _PluginInstance(
                plugin_id=plugin_data["plugin_id"],
                name=plugin_data["name"],
                settings=dict(plugin_data.get("plugin_settings", {})),
                refresh=dict(plugin_data.get("refresh", {})),
            )
        )
        return True


class _PlaylistManager:
    def __init__(self):
        self.playlists: list[_Playlist] = []

    def find_plugin(self, plugin_id: str, instance: str):
        for playlist in self.playlists:
            plugin = playlist.find_plugin(plugin_id, instance)
            if plugin:
                return plugin
        return None

    def add_plugin_to_playlist(self, playlist_name: str, plugin_data: dict[str, Any]):
        playlist = self.get_playlist(playlist_name)
        if not playlist:
            return False
        return playlist.add_plugin(plugin_data)

    def get_playlist(self, playlist_name: str):
        return next((pl for pl in self.playlists if pl.name == playlist_name), None)

    def add_playlist(self, name: str):
        playlist = _Playlist(name=name)
        self.playlists.append(playlist)
        return True

    def to_dict(self):
        return {
            "playlists": [
                {
                    "name": pl.name,
                    "plugins": [
                        {
                            "plugin_id": inst.plugin_id,
                            "name": inst.name,
                            "settings": dict(inst.settings),
                            "refresh": dict(inst.refresh),
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
        self.update_calls: list[dict[str, Any]] = []

    def get_plugin(self, plugin_id: str):
        return self.plugin_config

    def update_atomic(self, update_fn):
        payload: dict[str, Any] = {}
        update_fn(payload)
        self.update_calls.append(payload)


class _Plugin:
    def __init__(self, validation_error: str | None = None):
        self.validation_error = validation_error

    def validate_settings(self, settings: dict[str, Any]):
        return self.validation_error


def _playlist_workflows_mod() -> ModuleType:
    return importlib.import_module("services.playlist_workflows")


def test_normalize_instance_name_trims_and_validates():
    playlist_workflows_mod = _playlist_workflows_mod()

    name, err = playlist_workflows_mod.normalize_instance_name("  My Instance  ")
    assert err is None
    assert name == "My Instance"


def test_normalize_instance_name_rejects_bad_value():
    playlist_workflows_mod = _playlist_workflows_mod()

    name, err = playlist_workflows_mod.normalize_instance_name(" ")
    assert name is None
    assert err is not None
    assert err.field == "instance_name"
    assert err.status == 422


def test_validate_plugin_refresh_settings_interval():
    playlist_workflows_mod = _playlist_workflows_mod()

    refresh_config, err = playlist_workflows_mod.validate_plugin_refresh_settings(
        {
            "refreshType": "interval",
            "unit": "minute",
            "interval": "10",
        }
    )
    assert err is None
    assert refresh_config == {"interval": 600}


def test_validate_plugin_refresh_settings_scheduled():
    playlist_workflows_mod = _playlist_workflows_mod()

    refresh_config, err = playlist_workflows_mod.validate_plugin_refresh_settings(
        {
            "refreshType": "scheduled",
            "refreshTime": "08:30",
        }
    )
    assert err is None
    assert refresh_config == {"scheduled": "08:30"}


def test_build_playlist_plugin_dict_copies_inputs():
    playlist_workflows_mod = _playlist_workflows_mod()
    refresh = {"interval": 600}
    settings = {"city": "London"}
    result = playlist_workflows_mod.build_playlist_plugin_dict(
        "weather", settings, refresh, "Weather 1"
    )

    assert result == {
        "plugin_id": "weather",
        "refresh": {"interval": 600},
        "plugin_settings": {"city": "London"},
        "name": "Weather 1",
    }
    refresh["interval"] = 1200
    settings["city"] = "Paris"
    assert result["refresh"] == {"interval": 600}
    assert result["plugin_settings"] == {"city": "London"}


def test_prepare_add_plugin_workflow_happy_path():
    playlist_workflows_mod = _playlist_workflows_mod()
    device_config = _DeviceConfig(plugin_config={"id": "weather"})
    manager = device_config.playlist_manager
    manager.add_playlist("Morning")

    result = playlist_workflows_mod.prepare_add_plugin_workflow(
        "weather",
        {"city": "London"},
        {
            "playlist": "Morning",
            "instance_name": "Morning Weather",
            "refreshType": "interval",
            "unit": "minute",
            "interval": "10",
        },
        playlist_manager=manager,
        device_config=device_config,
    )

    assert isinstance(result, playlist_workflows_mod.AddPluginWorkflowResult)
    assert result.ok is True
    assert result.playlist_name == "Morning"
    assert result.instance_name == "Morning Weather"
    assert result.refresh_config == {"interval": 600}
    assert result.plugin_dict == {
        "plugin_id": "weather",
        "refresh": {"interval": 600},
        "plugin_settings": {"city": "London"},
        "name": "Morning Weather",
    }
    assert manager.find_plugin("weather", "Morning Weather") is not None


def test_prepare_add_plugin_workflow_rejects_duplicate_instance():
    playlist_workflows_mod = _playlist_workflows_mod()
    device_config = _DeviceConfig(plugin_config={"id": "weather"})
    manager = device_config.playlist_manager
    manager.add_playlist("Morning")
    manager.add_plugin_to_playlist(
        "Morning",
        {
            "plugin_id": "weather",
            "name": "Morning Weather",
            "refresh": {"interval": 600},
            "plugin_settings": {"city": "Paris"},
        },
    )

    result = playlist_workflows_mod.prepare_add_plugin_workflow(
        "weather",
        {"city": "London"},
        {
            "playlist": "Morning",
            "instance_name": "Morning Weather",
            "refreshType": "interval",
            "unit": "minute",
            "interval": "10",
        },
        playlist_manager=manager,
        device_config=device_config,
    )

    assert result.ok is False
    assert result.error is not None
    assert result.error.message == "Plugin instance 'Morning Weather' already exists"
    assert result.error.field == "instance_name"


def test_prepare_add_plugin_workflow_rejects_missing_playlist():
    playlist_workflows_mod = _playlist_workflows_mod()
    device_config = _DeviceConfig(plugin_config={"id": "weather"})
    result = playlist_workflows_mod.prepare_add_plugin_workflow(
        "weather",
        {"city": "London"},
        {
            "playlist": "",
            "instance_name": "Morning Weather",
            "refreshType": "interval",
            "unit": "minute",
            "interval": "10",
        },
        playlist_manager=device_config.playlist_manager,
        device_config=device_config,
    )

    assert result.ok is False
    assert result.error is not None
    assert result.error.message == "Playlist name is required"
    assert result.error.field == "playlist"


def test_prepare_add_plugin_workflow_rejects_security_error(monkeypatch):
    device_config = _DeviceConfig(plugin_config={"id": "weather"})
    manager = device_config.playlist_manager
    manager.add_playlist("Morning")
    playlist_workflows_mod = _playlist_workflows_mod()

    monkeypatch.setattr(
        playlist_workflows_mod,
        "validate_plugin_settings_security",
        lambda device_config, plugin_id, plugin_settings: playlist_workflows_mod.WorkflowError(
            "bad input", status=400, field="city"
        ),
    )

    result = playlist_workflows_mod.prepare_add_plugin_workflow(
        "weather",
        {"city": "London"},
        {
            "playlist": "Morning",
            "instance_name": "Morning Weather",
            "refreshType": "interval",
            "unit": "minute",
            "interval": "10",
        },
        playlist_manager=manager,
        device_config=device_config,
    )

    assert result.ok is False
    assert result.error is not None
    assert result.error.message == "bad input"
