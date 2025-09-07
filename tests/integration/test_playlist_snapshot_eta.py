# pyright: reportMissingImports=false
import re
from datetime import datetime, timezone

from model import RefreshInfo


def _fixed_now(_device_config):
    # 2025-01-01 08:00:00 UTC for deterministic snapshots/ETA
    return datetime(2025, 1, 1, 8, 0, 0, tzinfo=timezone.utc)


def _prepare_playlist_state(device_config_dev):
    pm = device_config_dev.get_playlist_manager()
    if not pm.get_playlist("Default"):
        pm.add_playlist("Default", "00:00", "24:00")
    pl = pm.get_playlist("Default")
    # Three interval-based instances
    pl.add_plugin(
        {
            "plugin_id": "clock",
            "name": "Clock A",
            "plugin_settings": {},
            "refresh": {"interval": 300},  # 5m
        }
    )
    pl.add_plugin(
        {
            "plugin_id": "weather",
            "name": "Weather B",
            "plugin_settings": {},
            "refresh": {"interval": 300},
        }
    )
    pl.add_plugin(
        {
            "plugin_id": "calendar",
            "name": "Calendar C",
            "plugin_settings": {},
            "refresh": {"interval": 300},
        }
    )

    # Last refresh was 07:55 on this playlist so next tick at 08:00 (in 5min window)
    device_config_dev.refresh_info = RefreshInfo(
        refresh_type="Playlist",
        plugin_id="clock",
        refresh_time="2025-01-01T07:55:00+00:00",
        image_hash=0,
        playlist="Default",
        plugin_instance="Clock A",
    )
    device_config_dev.write_config()


def test_eta_math_renders_expected(client, device_config_dev, monkeypatch):
    monkeypatch.setattr("utils.time_utils.now_device_tz", _fixed_now, raising=True)
    # Patch the imported alias used inside blueprints.playlist
    monkeypatch.setattr("blueprints.playlist.now_device_tz", _fixed_now, raising=True)
    _prepare_playlist_state(device_config_dev)

    resp = client.get("/playlist")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")

    # Expect ETA sequence for the three instances
    found = re.findall(r"Next in(?:\s+\d+h)?\s+(\d+)m\s+• at\s+(\d{2}:\d{2})", html)
    assert ("5", "08:05") in found
    assert ("10", "08:10") in found
    assert ("15", "08:15") in found


