"""Loading the last-refresh record when the app starts.

A damaged or missing record must never stop the app from starting; it
falls back to an empty "Manual Update" entry and logs a warning.
"""

import json
import logging
from pathlib import Path
from typing import Any

import pytest

_VALID_RECORD = {
    "refresh_type": "Playlist",
    "plugin_id": "weather",
    "refresh_time": "2025-06-01T12:00:00",
    "image_hash": "xyz",
    "playlist": "Default",
    "plugin_instance": "Weather 1",
    "display_ms": 812,
}

# Stands for "no refresh_info key at all" in the saved config.
_MISSING = object()


def _load(monkeypatch: Any, tmp_path: Path, refresh_info: Any) -> Any:
    import config as config_mod

    cfg: dict[str, Any] = {
        "name": "RefreshInfoLoad",
        "display_type": "mock",
        "resolution": [800, 480],
        "orientation": "horizontal",
        "playlist_config": {"playlists": [], "active_playlist": ""},
    }
    if refresh_info is not _MISSING:
        cfg["refresh_info"] = refresh_info
    cfg_path = tmp_path / "device.json"
    cfg_path.write_text(json.dumps(cfg))
    monkeypatch.setattr(config_mod.Config, "config_file", str(cfg_path))
    return config_mod.Config()


def test_valid_record_is_loaded_with_its_optional_fields(
    monkeypatch: Any, tmp_path: Path
) -> None:
    info = _load(monkeypatch, tmp_path, _VALID_RECORD).get_refresh_info()

    assert info.refresh_type == "Playlist"
    assert info.plugin_id == "weather"
    assert info.refresh_time == "2025-06-01T12:00:00"
    assert info.image_hash == "xyz"
    assert info.playlist == "Default"
    assert info.plugin_instance == "Weather 1"
    assert info.display_ms == 812


def test_valid_record_survives_a_save_round_trip(
    monkeypatch: Any, tmp_path: Path
) -> None:
    info = _load(monkeypatch, tmp_path, _VALID_RECORD).get_refresh_info()

    assert info.to_dict() == _VALID_RECORD


@pytest.mark.parametrize(
    "refresh_info",
    [
        pytest.param(_MISSING, id="absent"),
        pytest.param({}, id="empty"),
        pytest.param({"refresh_type": "Playlist"}, id="missing-keys"),
    ],
)
def test_damaged_record_falls_back_to_an_empty_manual_entry(
    monkeypatch: Any,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    refresh_info: Any,
) -> None:
    with caplog.at_level(logging.WARNING, logger="config"):
        info = _load(monkeypatch, tmp_path, refresh_info).get_refresh_info()

    assert info.refresh_type == "Manual Update"
    assert info.plugin_id == ""
    assert info.refresh_time is None
    assert info.image_hash is None
    assert "Invalid refresh_info in config" in caplog.text
