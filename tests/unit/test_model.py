# pyright: reportMissingImports=false
from datetime import datetime, timedelta
import pytz

from model import PlaylistManager, Playlist, PluginInstance


def test_should_refresh_interval_true():
    now = datetime(2025, 1, 1, 12, 0, 0)
    last = now - timedelta(seconds=3601)
    assert PlaylistManager.should_refresh(last, 3600, now) is True


def test_should_refresh_interval_false():
    now = datetime(2025, 1, 1, 12, 0, 0)
    last = now - timedelta(seconds=3599)
    assert PlaylistManager.should_refresh(last, 3600, now) is False


def test_determine_active_playlist_priority():
    tz = pytz.UTC
    now = datetime(2025, 1, 1, 12, 0, 0, tzinfo=tz)
    p1 = Playlist("All Day", "00:00", "24:00", plugins=[{"plugin_id": "x", "name": "a", "plugin_settings": {}, "refresh": {"interval": 300}}])
    p2 = Playlist("Lunch", "11:30", "13:30", plugins=[{"plugin_id": "x", "name": "b", "plugin_settings": {}, "refresh": {"interval": 300}}])
    pm = PlaylistManager([p1, p2])
    active = pm.determine_active_playlist(now)
    assert active.name == "Lunch"


def test_plugin_instance_should_refresh_interval_and_scheduled():
    tz = pytz.UTC
    now = datetime(2025, 1, 1, 13, 0, 0, tzinfo=tz)
    pi = PluginInstance("x", "inst", {}, {"interval": 300}, latest_refresh_time=(now - timedelta(seconds=301)).isoformat())
    assert pi.should_refresh(now) is True

    # With scheduled in the past today -> True if not refreshed yet after schedule
    pi = PluginInstance("x", "inst", {}, {"scheduled": "12:00"}, latest_refresh_time=(now - timedelta(hours=2)).isoformat())
    assert pi.should_refresh(now) is True


def test_get_time_range_minutes():
    p = Playlist("Morning", "06:00", "09:30")
    assert p.get_time_range_minutes() == 210


