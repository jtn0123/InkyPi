"""A reorder changes only order; invalid permutations must never save."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from flask.testing import FlaskClient

from config import Config
from model import Playlist, PluginInstance
from utils.request_models import parse_playlist_reorder_request


def _instances() -> list[PluginInstance]:
    return [
        PluginInstance("weather", "A", {}, {"interval": 60}),
        PluginInstance("weather", "B", {}, {"interval": 60}),
    ]


@pytest.mark.parametrize(
    "ordered",
    [
        [{"plugin_id": "weather", "name": "A"}] * 2,
        [{"plugin_id": "weather", "name": "A"}],
        [("weather", "A"), ("weather", "unknown")],
        [("weather", "A"), ([], "B")],
        [("weather", "A"), ("weather", {})],
        [
            ("weather", "A"),
            {"plugin_id": "weather", "name": [], "instance_name": "B"},
        ],
        [("weather", "A"), ("weather", None)],
        [("weather", "A"), ("", "B")],
        [("weather", "A"), ("weather", " ")],
        [("weather", "A"), ["weather"]],
        [("weather", "A"), ["weather", "B", "extra"]],
        [("weather", "A"), None],
        {"plugin_id": "weather", "name": "A"},
    ],
)
def test_model_rejects_invalid_permutation_without_mutation(ordered: object) -> None:
    playlist = Playlist("P", "00:00", "24:00")
    original = _instances()
    playlist.plugins = original
    playlist.current_plugin_index = 1

    assert playlist.reorder_plugins(ordered) is False
    assert playlist.plugins is original
    assert playlist.current_plugin_index == 1
    assert playlist.plugins[0] is original[0]
    assert playlist.plugins[1] is original[1]


def test_model_rejects_ambiguous_existing_identities() -> None:
    playlist = Playlist("P", "00:00", "24:00")
    original = _instances()
    original[1].name = "A"
    playlist.plugins = original

    assert playlist.reorder_plugins([("weather", "A")] * 2) is False
    assert playlist.plugins is original


def test_model_valid_permutation_preserves_instances_and_alias() -> None:
    playlist = Playlist("P", "00:00", "24:00")
    first, second = _instances()
    playlist.plugins = [first, second]
    playlist.current_plugin_index = 1

    assert (
        playlist.reorder_plugins(
            [{"plugin_id": "weather", "instance_name": "B"}, ("weather", "A")]
        )
        is True
    )
    assert playlist.plugins[0] is second
    assert playlist.plugins[1] is first
    assert playlist.current_plugin_index == 1


def test_empty_playlist_accepts_empty_permutation() -> None:
    playlist = Playlist("P", "00:00", "24:00")
    assert playlist.reorder_plugins([]) is True
    assert playlist.plugins == []


def test_parser_rejects_duplicate_normalized_identity() -> None:
    parsed, error = parse_playlist_reorder_request(
        {
            "playlist_name": "Default",
            "ordered": [
                {"plugin_id": "weather", "name": "A"},
                {"plugin_id": " weather ", "name": " A "},
            ],
        }
    )
    assert parsed is None
    assert error is not None
    assert error.status == 400
    assert error.field == "ordered"


@pytest.mark.parametrize(
    "ordered",
    [
        [{"plugin_id": "weather", "name": "A"}] * 2,
        [{"plugin_id": "weather", "name": "A"}],
        [
            {"plugin_id": "weather", "name": "A"},
            {"plugin_id": "weather", "name": "B"},
            {"plugin_id": "weather", "name": "C"},
        ],
        [
            {"plugin_id": "weather", "name": "A"},
            {"plugin_id": " weather ", "name": " A "},
        ],
        [
            {"plugin_id": "weather", "name": "A"},
            {"plugin_id": "weather", "name": "unknown"},
        ],
        [
            {"plugin_id": "weather", "name": "A"},
            {"plugin_id": [], "name": "B"},
        ],
        [
            {"plugin_id": "weather", "name": "A"},
            {"plugin_id": "weather", "name": {}},
        ],
        [None, {"plugin_id": "weather", "name": "B"}],
        [
            {"plugin_id": "weather", "name": "A"},
            {"plugin_id": "weather"},
        ],
        {"plugin_id": "weather", "name": "A"},
    ],
)
def test_route_rejection_preserves_live_identity_and_disk_without_save(
    client: FlaskClient, device_config_dev: Config, ordered: object
) -> None:
    cfg = device_config_dev
    manager = cfg.playlist_manager
    playlist = manager.playlists[0]
    first, second = _instances()
    playlist.plugins = [first, second]
    playlist.current_plugin_index = 1
    cfg.write_config()
    before = Path(cfg.config_file).read_bytes()
    hash_before = cfg._last_written_hash

    with patch.object(cfg, "write_config", wraps=cfg.write_config) as save:
        response = client.post(
            "/reorder_plugins",
            json={"playlist_name": playlist.name, "ordered": ordered},
        )
        assert response.status_code == 400
        save.assert_not_called()

    assert Path(cfg.config_file).read_bytes() == before
    assert cfg._last_written_hash == hash_before
    assert cfg.playlist_manager is manager
    assert manager.get_playlist(playlist.name) is playlist
    assert playlist.plugins[0] is first
    assert playlist.plugins[1] is second
    assert playlist.current_plugin_index == 1


def test_route_valid_permutation_saves_and_preserves_live_identity(
    client: FlaskClient, device_config_dev: Config
) -> None:
    cfg = device_config_dev
    manager = cfg.playlist_manager
    playlist = manager.playlists[0]
    first, second = _instances()
    playlist.plugins = [first, second]
    cfg.write_config()
    before = Path(cfg.config_file).read_bytes()

    with patch.object(cfg, "write_config", wraps=cfg.write_config) as save:
        response = client.post(
            "/reorder_plugins",
            json={
                "playlist_name": playlist.name,
                "ordered": [
                    {"plugin_id": "weather", "name": "B"},
                    {"plugin_id": "weather", "name": "A"},
                ],
            },
        )
        assert response.status_code == 200
        save.assert_called_once()

    assert Path(cfg.config_file).read_bytes() != before
    persisted = json.loads(Path(cfg.config_file).read_text())
    assert persisted["playlist_config"] == manager.to_dict()
    assert cfg.playlist_manager is manager
    assert manager.get_playlist(playlist.name) is playlist
    assert playlist.plugins[0] is second
    assert playlist.plugins[1] is first


def test_route_failed_save_restores_order_and_instance_identity(
    client: FlaskClient, device_config_dev: Config
) -> None:
    cfg = device_config_dev
    manager = cfg.playlist_manager
    playlist = manager.playlists[0]
    first, second = _instances()
    playlist.plugins = [first, second]
    playlist.current_plugin_index = 1
    cfg.write_config()
    before = Path(cfg.config_file).read_bytes()
    hash_before = cfg._last_written_hash

    with patch("config.os.replace", side_effect=OSError("injected save failure")):
        response = client.post(
            "/reorder_plugins",
            json={
                "playlist_name": playlist.name,
                "ordered": [
                    {"plugin_id": "weather", "name": "B"},
                    {"plugin_id": "weather", "name": "A"},
                ],
            },
        )
    assert response.status_code == 500
    assert Path(cfg.config_file).read_bytes() == before
    assert cfg._last_written_hash == hash_before
    assert cfg.playlist_manager is manager
    assert manager.get_playlist(playlist.name) is playlist
    assert playlist.plugins[0] is first
    assert playlist.plugins[1] is second
    assert playlist.current_plugin_index == 1
