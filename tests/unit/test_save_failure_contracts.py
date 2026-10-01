"""Observable save contracts using real temporary Config and atomic writes."""

import json
from pathlib import Path
from typing import Any

import pytest

from config import Config
from services.plugin_workflows import save_plugin_settings_workflow


class ValidPlugin:
    def validate_settings(self, settings: dict[str, Any]) -> None:
        return None


@pytest.fixture
def device(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    root = Path(__file__).resolve().parents[2]
    data = json.loads((root / "src/config/device_dev.json").read_text())
    data["playlist_config"] = {"playlists": [], "active_playlist": ""}
    path = tmp_path / "device.json"
    path.write_text(json.dumps(data))
    monkeypatch.setattr(Config, "config_file", str(path))
    for attr in [
        "current_image_file",
        "processed_image_file",
        "plugin_image_dir",
        "history_image_dir",
    ]:
        monkeypatch.setattr(Config, attr, str(tmp_path / attr))
    cfg = Config()
    cfg.playlist_manager.add_playlist("Other")
    cfg.playlist_manager.delete_playlist("Default")
    cfg.write_config()
    return cfg


def save(device: Config, **kwargs: Any) -> Any:
    return save_plugin_settings_workflow(
        "weather",
        {"city": "London"},
        device,
        device.playlist_manager,
        get_plugin_instance_fn=lambda _: ValidPlugin(),
        validate_required_fields_fn=lambda *_: None,
        record_change_fn=None,
        **kwargs,
    )


def test_absent_default_rolls_back_with_failed_write(
    device: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = Path(device.config_file).read_bytes()
    manager = device.playlist_manager
    original = manager.get_playlist("Other")

    def fail(*args: Any, **kwargs: Any) -> None:
        raise OSError("replacement failed")

    with monkeypatch.context() as patch:
        patch.setattr("config.os.replace", fail)
        result = save(device)
    assert not result.ok
    assert Path(device.config_file).read_bytes() == before
    assert manager.get_playlist("Default") is None
    assert manager.get_playlist("Other") is original
    assert save(device).ok
    assert manager.get_playlist("Default") is not None


@pytest.mark.parametrize("failure", ["load", "required", "schema"])
def test_unavailable_validation_never_mutates(device: Config, failure: str) -> None:
    before = Path(device.config_file).read_bytes()

    def fail(*args: Any, **kwargs: Any) -> None:
        raise ImportError("validator unavailable")

    class BrokenPlugin(ValidPlugin):
        def validate_settings(self, settings: dict[str, Any]) -> None:
            fail()

    result = save_plugin_settings_workflow(
        "weather",
        {},
        device,
        device.playlist_manager,
        get_plugin_instance_fn=(
            fail
            if failure == "load"
            else lambda _: BrokenPlugin() if failure == "schema" else ValidPlugin()
        ),
        validate_required_fields_fn=fail if failure == "required" else lambda *_: None,
        record_change_fn=None,
    )
    assert not result.ok
    assert result.error is not None
    assert result.error.status == 503
    assert result.error.code == "backend_unavailable"
    assert Path(device.config_file).read_bytes() == before
    assert device.playlist_manager.get_playlist("Default") is None


def test_history_failure_reports_committed_save(device: Config) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        raise OSError("history unavailable")

    result = save_plugin_settings_workflow(
        "weather",
        {"city": "London"},
        device,
        device.playlist_manager,
        get_plugin_instance_fn=lambda _: ValidPlugin(),
        validate_required_fields_fn=lambda *_: None,
        record_change_fn=fail,
    )
    assert result.ok
    assert result.warnings
    assert result.after_settings == {"city": "London"}
    persisted = json.loads(Path(device.config_file).read_text())
    default = next(
        p for p in persisted["playlist_config"]["playlists"] if p["name"] == "Default"
    )
    assert default["plugins"][0]["plugin_settings"] == {"city": "London"}


@pytest.mark.parametrize("route", ["save", "update"])
@pytest.mark.parametrize("failure", ["validation", "history", "replacement"])
def test_route_response_matches_persisted_state(
    device: Config, monkeypatch: pytest.MonkeyPatch, route: str, failure: str
) -> None:
    from flask import Flask

    from app_setup.error_handlers import register_error_handlers
    from blueprints.plugin import plugin_bp
    from utils.plugin_history import record_change

    manager = device.playlist_manager
    manager.add_playlist("Default")
    playlist = manager.get_playlist("Default")
    assert playlist is not None
    playlist.add_plugin(
        {
            "plugin_id": "weather",
            "name": "weather_saved_settings",
            "plugin_settings": {"city": "Paris"},
            "refresh": {"interval": 3600},
        }
    )
    device.write_config()
    before = Path(device.config_file).read_bytes()
    held = playlist.find_plugin("weather", "weather_saved_settings")
    app = Flask(__name__)
    app.config["DEVICE_CONFIG"] = device
    app.register_blueprint(plugin_bp)
    register_error_handlers(app)

    def fail(*args: Any, **kwargs: Any) -> None:
        raise OSError("injected failure")

    monkeypatch.setattr(
        "blueprints.plugin.get_plugin_instance",
        fail if failure == "validation" else lambda _: ValidPlugin(),
    )
    if failure == "history":

        def failed_history(*args: Any) -> bool:
            with monkeypatch.context() as patch:
                patch.setattr("utils.plugin_history.tempfile.mkstemp", fail)
                return record_change(*args)

        monkeypatch.setattr("blueprints.plugin._record_plugin_change", failed_history)
    if failure == "replacement":
        monkeypatch.setattr("config.os.replace", fail)
    client = app.test_client()
    if route == "save":
        response = client.post(
            "/save_plugin_settings", data={"plugin_id": "weather", "city": "London"}
        )
    else:
        response = client.put(
            "/update_plugin_instance/weather_saved_settings",
            data={"plugin_id": "weather", "city": "London"},
        )
    payload = response.get_json()
    assert payload is not None
    if failure == "history":
        assert response.status_code == 200
        assert payload["success"]
        assert payload["warnings"]
        assert held is not None and held.settings == {"city": "London"}
        persisted = json.loads(Path(device.config_file).read_text())
        default = next(
            p
            for p in persisted["playlist_config"]["playlists"]
            if p["name"] == "Default"
        )
        assert default["plugins"][0]["plugin_settings"] == {"city": "London"}
    else:
        assert response.status_code == (503 if failure == "validation" else 500)
        assert Path(device.config_file).read_bytes() == before
        assert playlist.find_plugin("weather", "weather_saved_settings") is held
        assert held is not None and held.settings == {"city": "Paris"}
