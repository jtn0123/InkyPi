"""Real-config import validation and transaction regressions (B6/B7)."""

from __future__ import annotations

import copy
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from threading import Barrier
from typing import Any
from unittest.mock import patch

import pytest
from flask import Flask
from flask.testing import FlaskClient
from werkzeug.test import TestResponse

from config import Config
from model import Playlist, PlaylistManager, PluginInstance


@dataclass(frozen=True)
class ImportState:
    disk: bytes
    config: dict[str, Any]
    manager: PlaylistManager
    serialized: dict[str, Any]
    playlists: tuple[Playlist, ...]
    plugins: tuple[tuple[PluginInstance, ...], ...]


def _capture(config: Config) -> ImportState:
    manager = config.get_playlist_manager()
    return ImportState(
        disk=Path(config.config_file).read_bytes(),
        config=copy.deepcopy(config.config),
        manager=manager,
        serialized=copy.deepcopy(manager.to_dict()),
        playlists=tuple(manager.playlists),
        plugins=tuple(tuple(playlist.plugins) for playlist in manager.playlists),
    )


def _assert_unchanged(config: Config, before: ImportState) -> None:
    manager = config.get_playlist_manager()
    assert Path(config.config_file).read_bytes() == before.disk
    assert config.config == before.config
    assert manager is before.manager
    assert manager.to_dict() == before.serialized
    assert len(manager.playlists) == len(before.playlists)
    for index, playlist in enumerate(manager.playlists):
        assert playlist is before.playlists[index]
        assert len(playlist.plugins) == len(before.plugins[index])
        for plugin_index, plugin in enumerate(playlist.plugins):
            assert plugin is before.plugins[index][plugin_index]


def _entry(
    plugin_id: str = "year_progress", name: str = "Imported", settings: object = None
) -> dict[str, object]:
    return {
        "plugin_id": plugin_id,
        "name": name,
        "settings": {} if settings is None else settings,
    }


def _post(client: FlaskClient, *instances: dict[str, object]) -> TestResponse:
    return client.post(
        "/api/plugins/import", json={"version": 1, "instances": list(instances)}
    )


def _seed(config: Config, *, default: bool = True) -> None:
    manager = config.get_playlist_manager()
    manager.playlists.clear()
    name = "Default" if default else "Existing"
    manager.add_playlist(name)
    playlist = manager.get_playlist(name)
    assert playlist is not None
    playlist.add_plugin(
        {
            "plugin_id": "year_progress",
            "name": "Original",
            "plugin_settings": {"sentinel": [1, 2]},
            "refresh": {"interval": 3600},
        }
    )
    config.write_config()


@pytest.mark.parametrize("field,value", [("latitude", "999"), ("longitude", "999")])
def test_invalid_weather_import_is_indexed_and_does_not_mutate(
    client: FlaskClient, device_config_dev: Config, field: str, value: str
) -> None:
    _seed(device_config_dev)
    before = _capture(device_config_dev)
    settings = {"latitude": "40", "longitude": "-74", field: value}
    response = _post(client, _entry("weather", settings=settings))
    assert response.status_code == 400
    body = response.get_json()
    assert "instances[0]" in body["error"]
    assert field.lower() in body["error"].lower()
    assert body["details"]["field"] == "instances[0].settings"
    _assert_unchanged(device_config_dev, before)


@pytest.mark.parametrize("settings", [None, False, [], "invalid", 12])
def test_import_rejects_malformed_installed_settings(
    client: FlaskClient, device_config_dev: Config, settings: object
) -> None:
    _seed(device_config_dev)
    before = _capture(device_config_dev)
    entry = _entry()
    entry["settings"] = settings
    response = _post(client, entry)
    assert response.status_code == 400
    assert "instances[0]" in response.get_json()["error"]
    _assert_unchanged(device_config_dev, before)


def test_optional_schema_import_still_runs_plugin_validator(
    client: FlaskClient, device_config_dev: Config
) -> None:
    _seed(device_config_dev)
    before = _capture(device_config_dev)
    with patch(
        "plugins.year_progress.year_progress.YearProgress.validate_settings",
        return_value="Year settings rejected",
    ) as validator:
        response = _post(client, _entry())
    assert response.status_code == 400
    assert "Year settings rejected" in response.get_json()["error"]
    validator.assert_called_once_with({})
    _assert_unchanged(device_config_dev, before)


@pytest.mark.parametrize("schema", [False, 0, "", [], {"sections": [False]}])
def test_malformed_plugin_schema_blocks_import(
    client: FlaskClient, device_config_dev: Config, schema: object
) -> None:
    _seed(device_config_dev)
    before = _capture(device_config_dev)
    with patch(
        "plugins.year_progress.year_progress.YearProgress.build_settings_schema",
        return_value=schema,
    ):
        response = _post(client, _entry())
    assert response.status_code == 503
    assert response.get_json()["code"] == "backend_unavailable"
    assert "instances[0]" in response.get_json()["error"]
    _assert_unchanged(device_config_dev, before)


@pytest.mark.parametrize("failure", ["loader", "schema", "validator"])
def test_unavailable_plugin_validation_blocks_import(
    client: FlaskClient, device_config_dev: Config, failure: str
) -> None:
    _seed(device_config_dev)
    before = _capture(device_config_dev)
    target = {
        "loader": "plugins.plugin_registry.get_plugin_instance",
        "schema": "plugins.year_progress.year_progress.YearProgress.build_settings_schema",
        "validator": "plugins.year_progress.year_progress.YearProgress.validate_settings",
    }[failure]
    with patch(target, side_effect=RuntimeError("Validator unavailable")):
        response = _post(client, _entry())
    assert response.status_code == 503
    assert response.get_json()["code"] == "backend_unavailable"
    _assert_unchanged(device_config_dev, before)


def test_late_invalid_entry_prevents_prior_valid_entry_and_default_creation(
    client: FlaskClient, device_config_dev: Config
) -> None:
    _seed(device_config_dev, default=False)
    before = _capture(device_config_dev)
    response = _post(
        client,
        _entry(name="Valid first"),
        _entry("weather", settings={"latitude": "999", "longitude": "0"}),
    )
    assert response.status_code == 400
    assert "instances[1]" in response.get_json()["error"]
    _assert_unchanged(device_config_dev, before)


@pytest.mark.parametrize("unknown_only", [False, True])
def test_zero_import_does_not_create_default_or_write(
    client: FlaskClient, device_config_dev: Config, unknown_only: bool
) -> None:
    _seed(device_config_dev, default=False)
    before = _capture(device_config_dev)
    entries = [_entry("not_installed")] if unknown_only else []
    with patch.object(
        device_config_dev, "write_config", wraps=device_config_dev.write_config
    ) as writer:
        response = _post(client, *entries)
    assert response.status_code == 200
    assert response.get_json()["imported"] == 0
    assert response.get_json()["skipped"] == (["not_installed"] if unknown_only else [])
    _assert_unchanged(device_config_dev, before)
    writer.assert_not_called()


def test_optional_schema_and_unknown_skip_import_persist_valid_settings(
    client: FlaskClient, device_config_dev: Config
) -> None:
    _seed(device_config_dev, default=False)
    settings = {"custom": {"items": [1, 2]}}
    response = _post(client, _entry(settings=settings), _entry("not_installed"))
    assert response.status_code == 200
    assert response.get_json()["imported"] == 1
    assert response.get_json()["skipped"] == ["not_installed"]
    persisted = json.loads(Path(device_config_dev.config_file).read_text())
    default = next(
        p for p in persisted["playlist_config"]["playlists"] if p["name"] == "Default"
    )
    assert default["plugins"][0]["plugin_settings"] == settings


def test_collision_names_include_other_playlists_and_prior_imports(
    client: FlaskClient, device_config_dev: Config
) -> None:
    _seed(device_config_dev, default=False)
    response = _post(client, _entry(name="Original"), _entry(name="Original"))
    assert response.status_code == 200
    assert response.get_json()["renamed"] == [
        "Original → Original (imported)",
        "Original → Original (imported 2)",
    ]
    manager = device_config_dev.get_playlist_manager()
    default = manager.get_playlist("Default")
    assert default is not None
    assert [p.name for p in default.plugins] == [
        "Original (imported)",
        "Original (imported 2)",
    ]
    persisted = json.loads(Path(device_config_dev.config_file).read_text())
    assert persisted["playlist_config"] == manager.to_dict()


@pytest.mark.parametrize("default", [False, True])
def test_import_replace_failure_rolls_back_existing_identity_and_disk(
    client: FlaskClient, device_config_dev: Config, default: bool
) -> None:
    _seed(device_config_dev, default=default)
    before = _capture(device_config_dev)
    with patch("config.os.replace", side_effect=OSError("Disk unavailable")):
        response = _post(client, _entry(name="Original"))
    assert response.status_code == 500
    _assert_unchanged(device_config_dev, before)
    assert list(Path(device_config_dev.config_file).parent.glob(".device.*.tmp")) == []


def test_late_addition_failure_rolls_back_earlier_addition_and_default(
    client: FlaskClient, device_config_dev: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(device_config_dev, default=False)
    before = _capture(device_config_dev)
    real_add = Playlist.add_plugin

    def fail_second(playlist: Playlist, data: dict[str, Any]) -> bool:
        if data["name"] == "Second":
            raise RuntimeError("Addition unavailable")
        return real_add(playlist, data)

    monkeypatch.setattr(Playlist, "add_plugin", fail_second)
    response = _post(client, _entry(name="First"), _entry(name="Second"))
    assert response.status_code == 500
    _assert_unchanged(device_config_dev, before)


def test_concurrent_imports_resolve_collisions_after_validation(
    flask_app: Flask, device_config_dev: Config
) -> None:
    """Both batches validate together, then commit distinct persisted names."""
    _seed(device_config_dev, default=False)
    rendezvous = Barrier(2)

    def synchronize_validation(_settings: dict[str, Any]) -> None:
        rendezvous.wait(timeout=5)

    def import_original() -> TestResponse:
        with flask_app.test_client() as concurrent_client:
            return _post(concurrent_client, _entry(name="Original"))

    with patch(
        "plugins.year_progress.year_progress.YearProgress.validate_settings",
        side_effect=synchronize_validation,
    ):
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(import_original) for _ in range(2)]
            responses = [future.result(timeout=10) for future in futures]

    assert [response.status_code for response in responses] == [200, 200]
    assert [response.get_json()["imported"] for response in responses] == [1, 1]
    manager = device_config_dev.get_playlist_manager()
    default = manager.get_playlist("Default")
    assert default is not None
    assert [plugin.name for plugin in default.plugins] == [
        "Original (imported)",
        "Original (imported 2)",
    ]
    persisted = json.loads(Path(device_config_dev.config_file).read_text())
    assert persisted["playlist_config"] == manager.to_dict()


@pytest.mark.parametrize("default", [False, True])
def test_late_addition_rejection_rolls_back_earlier_addition(
    client: FlaskClient,
    device_config_dev: Config,
    monkeypatch: pytest.MonkeyPatch,
    default: bool,
) -> None:
    _seed(device_config_dev, default=default)
    before = _capture(device_config_dev)
    real_add = Playlist.add_plugin

    def reject_second(playlist: Playlist, data: dict[str, Any]) -> bool:
        if data["name"] == "Second":
            return False
        return real_add(playlist, data)

    monkeypatch.setattr(Playlist, "add_plugin", reject_second)
    response = _post(client, _entry(name="First"), _entry(name="Second"))
    assert response.status_code == 500
    assert response.get_json()["code"] == "internal_error"
    _assert_unchanged(device_config_dev, before)
