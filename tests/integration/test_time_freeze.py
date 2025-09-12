# pyright: reportMissingImports=false
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
import pytz

pytest.importorskip("freezegun")
from freezegun import freeze_time


def test_playlist_rotation_respects_device_timezone_freeze(device_config_dev):
    # Configure device timezone to US/Eastern
    device_config_dev.update_value("timezone", "US/Eastern", write=True)

    # Create a playlist active between 08:00 and 10:00
    pm = device_config_dev.get_playlist_manager()
    pm.add_playlist("Morning", "08:00", "10:00")

    # Freeze time to 13:30 UTC (08:30 US/Eastern)
    with freeze_time("2025-01-01 13:30:00", tz_offset=0):
        # Determine active playlist using device-local current time
        from utils.time_utils import now_device_tz

        current_dt = now_device_tz(device_config_dev)
        playlist = pm.determine_active_playlist(current_dt)
        assert playlist is not None
        assert playlist.name == "Morning"


def test_refresh_cadence_interval_respects_device_timezone_freeze(
    device_config_dev, monkeypatch
):
    # Set device timezone
    device_config_dev.update_value("timezone", "US/Eastern", write=True)
    # Ensure a short plugin cycle interval (1 hour)
    device_config_dev.update_value("plugin_cycle_interval_seconds", 3600, write=True)

    # Prepare a playlist with a single plugin instance
    from model import RefreshInfo

    pm = device_config_dev.get_playlist_manager()
    pm.add_playlist("P1", "00:00", "24:00")
    pm.add_plugin_to_playlist(
        "P1",
        {
            "plugin_id": "ai_text",
            "name": "inst",
            "plugin_settings": {"title": "T"},
            "refresh": {"interval": 60},
        },
    )

    # Force determine_active_playlist to choose our playlist deterministically
    playlist = pm.get_playlist("P1")
    assert playlist is not None
    monkeypatch.setattr(
        pm, "determine_active_playlist", lambda dt: playlist, raising=True
    )

    # Latest refresh at 08:30 -0500
    device_config_dev.refresh_info = RefreshInfo(
        refresh_time="2025-01-01T08:30:00-05:00",
        image_hash="h",
        refresh_type="Playlist",
        plugin_id="ai_text",
    )

    from refresh_task import RefreshTask

    task = RefreshTask(device_config_dev, device_config_dev)  # display manager unused

    # 1) At 09:00 -0500 only 30 mins elapsed → NOT time to refresh
    with freeze_time("2025-01-01 14:00:00", tz_offset=0):  # 09:00 ET
        current_dt = task._get_current_datetime()
        p, inst = task._determine_next_plugin(
            pm, device_config_dev.get_refresh_info(), current_dt
        )
        assert p is None and inst is None

    # 2) At 10:00 -0500 90 mins elapsed → SHOULD refresh
    with freeze_time("2025-01-01 15:00:00", tz_offset=0):  # 10:00 ET
        current_dt = task._get_current_datetime()
        p, inst = task._determine_next_plugin(
            pm, device_config_dev.get_refresh_info(), current_dt
        )
        assert p is not None and inst is not None


def test_logs_api_uses_device_timezone_for_since(client, flask_app, monkeypatch):
    # Switch device tz
    dc = flask_app.config["DEVICE_CONFIG"]
    dc.update_value("timezone", "US/Eastern", write=True)

    # Stub journal reader parts to capture the seek timestamp
    import blueprints.settings as settings_mod

    captured: dict[str, int] = {"since_usec": 0}

    class FakeJR:
        def open(self, mode):
            return None

        def add_filter(self, rule):
            return None

        def seek_realtime_usec(self, usec):
            captured["since_usec"] = int(usec)

        def __iter__(self):
            return iter(())

    monkeypatch.setattr(settings_mod, "JOURNAL_AVAILABLE", True, raising=True)
    monkeypatch.setattr(settings_mod, "JournalReader", FakeJR, raising=True)
    monkeypatch.setattr(
        settings_mod, "JournalOpenMode", type("M", (), {"SYSTEM": object()})
    )
    monkeypatch.setattr(settings_mod, "Rule", lambda *a, **k: (a, k))

    # Freeze to 08:00 ET and request 2 hours
    with freeze_time("2025-01-01 13:00:00", tz_offset=0):  # 08:00 ET
        resp = client.get("/api/logs?hours=2")
        assert resp.status_code == 200

        # Expected since is 06:00 ET → compute in ET
        tz = pytz.timezone("US/Eastern")
        now_et = datetime.now(tz)
        since_et = (now_et - timedelta(hours=2)).timestamp()
        expected_usec = int(since_et * 1_000_000)

        assert captured["since_usec"] == expected_usec
